import os
from time import time as timer

import gym
import numpy as np
import numpy.random as rd
import torch
import torch.nn as nn

from AgentNetwork import QNetwork  # QLearning
from AgentNetwork import ActorDPG, Critic
from AgentNetwork import ActorDL, CriticSN  # SN_AC
from AgentNetwork import ActorCritic  # IntelAC
from AgentNetwork import CriticTwin  # TD3, SAC
from AgentNetwork import ActorPPO, CriticAdvantage  # PPO
from AgentNetwork import ActorSAC  # SAC

"""
2019-07-01 Zen4Jia1Hao2, GitHub: YonV1943 DL_RL_Zoo/RL
2019-11-11 Issay-0.0 [Essay Consciousness]
2020-02-02 Issay-0.1 Deep Learning Techniques (spectral norm, DenseNet, etc.) 
2020-04-04 Issay-0.1 [An Essay of Consciousness by YonV1943], IntelAC
2020-04-20 Issay-0.2 SN_AC, IntelAC_UnitedLoss
2020-05-20 Issay-0.3 [Essay, LongDear's Cerebellum (Little Brain)]
2020-05-27 Issay-0.3 Pipeline Update for SAC
2020-06-06 Issay-0.3 check PPO, SAC. Plan to add discrete SAC.

I consider that Reinforcement Learning Algorithms before 2020 have not consciousness
They feel more like a Cerebellum (Little Brain) for Machines.

Refer: (TD3) https://github.com/sfujim/TD3
Refer: (TD3) https://github.com/nikhilbarhate99/TD3-PyTorch-BipedalWalker-v2
Refer: (PPO) https://github.com/zhangchuheng123/Reinforcement-Implementation/blob/master/code/ppo.py
Refer: (PPO) https://github.com/Jiankai-Sun/Proximal-Policy-Optimization-in-Pytorch/blob/master/ppo.py
Refer: (PPO) https://github.com/openai/baselines/tree/master/baselines/ppo2
Refer: (SAC) https://github.com/TianhongDai/reinforcement-learning-algorithms/tree/master/rl_algorithms/sac
"""


class AgentDDPG:  # DEMO (tutorial only, simplify, low effective)
    def __init__(self, state_dim, action_dim, net_dim):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        self.act = ActorDPG(state_dim, action_dim, net_dim).to(self.device)
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=2e-4)

        self.act_target = ActorDPG(state_dim, action_dim, net_dim).to(self.device)
        self.act_target.load_state_dict(self.act.state_dict())

        self.cri = Critic(state_dim, action_dim, net_dim).to(self.device)
        self.cri_optimizer = torch.optim.Adam(self.cri.parameters(), lr=2e-4)

        self.cri_target = Critic(state_dim, action_dim, net_dim).to(self.device)
        self.cri_target.load_state_dict(self.cri.state_dict())

        self.criterion = nn.MSELoss()

        '''training record'''
        self.step_sum = 0

        '''extension'''
        self.ou_noise = OrnsteinUhlenbeckProcess(size=action_dim, sigma=0.3)
        # OU-Process has too much hyper-parameters.

    def update_buffer(self, env, memo, max_step, max_action, reward_scale, gamma):
        state = env.reset()
        step_sum = 1
        reward_sum = 0.0

        for t in range(max_step):
            '''inactive with environment'''
            action = self.select_actions((state,))[0]
            action += self.ou_noise()
            next_state, reward, done, _ = env.step(action * max_action)

            reward_sum += reward
            step_sum += 1

            '''update replay buffer'''
            reward_ = reward * reward_scale
            mask = 0.0 if done else gamma
            memo.add_memo((reward_, mask, state, action, next_state))

            state = next_state
            if done:
                break
        self.step_sum = step_sum
        return (reward_sum,), (step_sum,)

    def update_parameters(self, memo, _max_step, batch_size, _update_gap):
        loss_a_sum = 0.0
        loss_c_sum = 0.0

        # Here, the step_sum we interact in env is equal to the parameters update times
        update_times = self.step_sum
        for _ in range(update_times):
            with torch.no_grad():
                rewards, masks, states, actions, next_states = memo.random_sample(batch_size, self.device)

                next_action = self.act_target(next_states)
                next_q_target = self.cri_target(next_states, next_action)
                q_target = rewards + masks * next_q_target

            """critic loss"""
            q_eval = self.cri(states, actions)
            critic_loss = self.criterion(q_eval, q_target)
            loss_c_sum += critic_loss.item()

            self.cri_optimizer.zero_grad()
            critic_loss.backward()
            self.cri_optimizer.step()

            """actor loss"""
            action_cur = self.act(states)
            actor_loss = -self.cri(states, action_cur).mean()  # update parameters by sample policy gradient
            loss_a_sum += actor_loss.item()

            self.act_optimizer.zero_grad()
            actor_loss.backward()
            self.act_optimizer.step()

            self.soft_target_update(self.act_target, self.act)
            self.soft_target_update(self.cri_target, self.cri)

        loss_a_avg = loss_a_sum / update_times
        loss_c_avg = loss_c_sum / update_times
        return loss_a_avg, loss_c_avg

    def select_actions(self, states, explore_noise=0.0):  # CPU array to GPU tensor to CPU array
        states = torch.tensor(states, dtype=torch.float32, device=self.device)
        actions = self.act(states, explore_noise).cpu().data.numpy()
        return actions

    @staticmethod
    def soft_target_update(target, source, tau=5e-3):
        for target_param, param in zip(target.parameters(), source.parameters()):
            target_param.data.copy_(tau * param.data + (1.0 - tau) * target_param.data)

    def save_or_load_model(self, mod_dir, is_save):  # 2020-05-20
        act_save_path = '{}/actor.pth'.format(mod_dir)
        cri_save_path = '{}/critic.pth'.format(mod_dir)

        if is_save:
            torch.save(self.act.state_dict(), act_save_path)
            torch.save(self.cri.state_dict(), cri_save_path)
            # print("Saved act and cri:", mod_dir)
        elif os.path.exists(act_save_path):
            act_dict = torch.load(act_save_path, map_location=lambda storage, loc: storage)
            self.act.load_state_dict(act_dict)
            self.act_target.load_state_dict(act_dict)
            cri_dict = torch.load(cri_save_path, map_location=lambda storage, loc: storage)
            self.cri.load_state_dict(cri_dict)
            self.cri_target.load_state_dict(cri_dict)
        else:
            print("FileNotFound when load_model: {}".format(mod_dir))


class AgentBasicAC:  # DEMO (formal, basic Actor-Critic Methods, Policy Gradient)
    def __init__(self, state_dim, action_dim, net_dim):
        use_densenet = False  # soft target update is conflict with use_densenet
        use_sn = False  # soft target update is conflict with use_sn (Spectral Normalization)
        self.learning_rate = 4e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        actor_dim = net_dim
        self.act = ActorDL(state_dim, action_dim, actor_dim, use_densenet).to(self.device)
        self.act.train()
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=self.learning_rate * 0.5)

        self.act_target = ActorDL(state_dim, action_dim, actor_dim, use_densenet).to(self.device)
        self.act_target.eval()
        self.act_target.load_state_dict(self.act.state_dict())

        critic_dim = int(net_dim * 1.25)
        self.cri = CriticSN(state_dim, action_dim, critic_dim, use_densenet, use_sn).to(self.device)
        self.cri.train()
        self.cri_optimizer = torch.optim.Adam(self.cri.parameters(), lr=self.learning_rate)

        self.cri_target = CriticSN(state_dim, action_dim, critic_dim, use_densenet, use_sn).to(self.device)
        self.cri_target.eval()
        self.cri_target.load_state_dict(self.cri.state_dict())

        self.criterion = nn.SmoothL1Loss()

        '''training record'''
        self.state = None  # env.reset()
        self.reward_sum = 0.0
        self.step_sum = 0
        self.update_counter = 0  # delay update counter

    def update_buffer(self, env, buffer, max_step, max_action, reward_scale, gamma):
        explore_rate = 0.5  # explore rate when update_buffer()
        explore_noise = 0.2  # standard deviation of explore noise
        self.act.eval()

        rewards = list()
        steps = list()
        for t in range(max_step):
            '''inactive with environment'''
            explore_noise_temp = explore_noise if rd.rand() < explore_rate else 0
            action = self.select_actions((self.state,), explore_noise_temp)[0]
            next_state, reward, done, _ = env.step(action * max_action)

            self.reward_sum += reward
            self.step_sum += 1

            '''update replay buffer'''
            reward_ = reward * reward_scale
            mask = 0.0 if done else gamma
            buffer.add_memo((reward_, mask, self.state, action, next_state))

            self.state = next_state
            if done:
                rewards.append(self.reward_sum)
                self.reward_sum = 0.0

                steps.append(self.step_sum)
                self.step_sum = 0

                self.state = env.reset()
        return rewards, steps

    def update_parameters(self, buffer, max_step, batch_size, repeat_times):
        policy_noise = 0.2  # standard deviation of policy noise
        update_freq = 2  # delay update frequency, for soft target update
        self.act.train()

        loss_a_sum = 0.0
        loss_c_sum = 0.0

        k = 1.0 + buffer.now_len / buffer.max_len
        batch_size_ = int(batch_size * k)
        update_times = int(max_step * k)

        for i in range(update_times * repeat_times):
            with torch.no_grad():
                reward, mask, state, action, next_state = buffer.random_sample(batch_size_, self.device)

                next_action = self.act_target(next_state, policy_noise)
                q_target = self.cri_target(next_state, next_action)
                q_target = reward + mask * q_target

            '''critic_loss'''
            q_eval = self.cri(state, action)
            critic_loss = self.criterion(q_eval, q_target)
            loss_c_sum += critic_loss.item()

            self.cri_optimizer.zero_grad()
            critic_loss.backward()
            self.cri_optimizer.step()

            '''actor_loss'''
            if i % repeat_times == 0:
                action_pg = self.act(state)  # policy gradient
                actor_loss = -self.cri(state, action_pg).mean()  # policy gradient
                loss_a_sum += actor_loss.item()

                self.act_optimizer.zero_grad()
                actor_loss.backward()
                self.act_optimizer.step()

            '''soft target update'''
            self.update_counter += 1
            if self.update_counter == update_freq:
                self.update_counter = 0
                self.soft_target_update(self.act_target, self.act)  # soft target update
                self.soft_target_update(self.cri_target, self.cri)  # soft target update

        loss_a_avg = loss_a_sum / update_times
        loss_c_avg = loss_c_sum / (update_times * repeat_times)
        return loss_a_avg, loss_c_avg

    def select_actions(self, states, explore_noise=0.0):  # CPU array to GPU tensor to CPU array
        states = torch.tensor(states, dtype=torch.float32, device=self.device)
        actions = self.act(states, explore_noise).cpu().data.numpy()
        return actions

    @staticmethod
    def soft_target_update(target, source, tau=5e-3):
        for target_param, param in zip(target.parameters(), source.parameters()):
            target_param.data.copy_(tau * param.data + (1.0 - tau) * target_param.data)

    def save_or_load_model(self, mod_dir, is_save):  # 2020-05-20
        act_save_path = '{}/actor.pth'.format(mod_dir)
        cri_save_path = '{}/critic.pth'.format(mod_dir)

        if is_save:
            torch.save(self.act.state_dict(), act_save_path)
            torch.save(self.cri.state_dict(), cri_save_path)
            # print("Saved act and cri:", mod_dir)
        elif os.path.exists(act_save_path):
            act_dict = torch.load(act_save_path, map_location=lambda storage, loc: storage)
            self.act.load_state_dict(act_dict)
            self.act_target.load_state_dict(act_dict)
            cri_dict = torch.load(cri_save_path, map_location=lambda storage, loc: storage)
            self.cri.load_state_dict(cri_dict)
            self.cri_target.load_state_dict(cri_dict)
        else:
            print("FileNotFound when load_model: {}".format(mod_dir))


class AgentSNAC(AgentBasicAC):
    def __init__(self, state_dim, action_dim, net_dim):
        super(AgentBasicAC, self).__init__()
        use_densenet = True  # SNAC
        use_sn = True  # SNAC, use_sn (Spectral Normalization)
        self.learning_rate = 4e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        actor_dim = net_dim
        self.act = ActorDL(state_dim, action_dim, actor_dim, use_densenet).to(self.device)
        self.act.train()
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=self.learning_rate * 0.5)

        self.act_target = ActorDL(state_dim, action_dim, actor_dim, use_densenet).to(self.device)
        self.act_target.eval()
        self.act_target.load_state_dict(self.act.state_dict())

        critic_dim = int(net_dim * 1.25)
        self.cri = CriticSN(state_dim, action_dim, critic_dim, use_densenet, use_sn).to(self.device)
        self.cri.train()
        self.cri_optimizer = torch.optim.Adam(self.cri.parameters(), lr=self.learning_rate)

        self.cri_target = CriticSN(state_dim, action_dim, critic_dim, use_densenet, use_sn).to(self.device)
        self.cri_target.eval()
        self.cri_target.load_state_dict(self.cri.state_dict())

        self.criterion = nn.SmoothL1Loss()

        '''training record'''
        self.state = None  # env.reset()
        self.reward_sum = 0.0
        self.step_sum = 0
        self.update_counter = 0

        '''extension'''
        self.loss_c_sum = 0.0
        self.rho = 0.5

    def update_parameters(self, buffer, max_step, batch_size, repeat_times):
        policy_noise = 0.4  # standard deviation of policy noise
        update_freq = 2 ** 7  # delay update frequency, for hard target update
        self.act.train()

        loss_a_sum = 0.0
        loss_c_sum = 0.0

        k = 1.0 + buffer.now_len / buffer.max_len
        batch_size_ = int(batch_size * k)
        update_times = int(max_step * k)

        for i in range(update_times * repeat_times):
            with torch.no_grad():
                reward, mask, state, action, next_state = buffer.random_sample(batch_size_, self.device)

                next_a = self.act_target(next_state)
                next_a_noisy = self.act_target.add_noise(next_a, policy_noise)
                next_q = self.cri_target(next_state, next_a)
                next_q_noisy = self.cri_target(next_state, next_a_noisy)
                next_q_target = (next_q + next_q_noisy) * 0.5  # SNAC, more smooth and more stable q value
                next_q_target = reward + mask * next_q_target

            '''critic_loss'''
            q_eval = self.cri(state, action)
            critic_loss = self.criterion(q_eval, next_q_target)
            loss_c_tmp = critic_loss.item()
            loss_c_sum += loss_c_tmp
            self.loss_c_sum += loss_c_tmp  # extension

            self.cri_optimizer.zero_grad()
            critic_loss.backward()
            self.cri_optimizer.step()

            '''actor_loss'''
            if i % repeat_times == 0 and self.rho > 0.001:  # 2.6
                actions_pg = self.act(state)  # policy gradient
                actor_loss = -self.cri(state, actions_pg).mean()  # policy gradient
                loss_a_sum += actor_loss.item()

                self.act_optimizer.zero_grad()
                actor_loss.backward()
                # https://stackoverflow.com/questions/54716377/
                # how-to-do-gradient-clipping-in-pytorch/54716953#54716953
                # torch.nn.utils.clip_grad_norm_(self.act.parameters(), max_norm=4)
                self.act_optimizer.step()

            '''target update'''
            self.update_counter += 1
            if self.update_counter == update_freq:
                self.update_counter = 0
                self.cri_target.load_state_dict(self.cri.state_dict())  # hard target update
                self.act_target.load_state_dict(self.act.state_dict())  # hard target update

                rho = np.exp(-(self.loss_c_sum / update_freq) ** 2)
                self.rho = (self.rho + rho) * 0.5
                self.act_optimizer.param_groups[0]['lr'] = self.learning_rate * self.rho
                self.loss_c_sum = 0.0

        loss_a_avg = loss_a_sum / update_times
        loss_c_avg = loss_c_sum / (update_times * repeat_times)
        return loss_a_avg, loss_c_avg


class AgentInterAC(AgentBasicAC):
    def __init__(self, state_dim, action_dim, net_dim):
        super(AgentBasicAC, self).__init__()
        use_densenet = True
        # use_sn = True  # SNAC, use_sn (Spectral Normalization)
        self.learning_rate = 4e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        self.act = ActorCritic(state_dim, action_dim, net_dim, use_densenet).to(self.device)
        self.act.train()
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=self.learning_rate)

        self.act_target = ActorCritic(state_dim, action_dim, net_dim, use_densenet).to(self.device)
        self.act_target.eval()
        self.act_target.load_state_dict(self.act.state_dict())

        self.criterion = nn.SmoothL1Loss()

        '''training record'''
        self.state = None  # env.reset()
        self.reward_sum = 0.0
        self.step_sum = 0
        self.update_counter = 0

        '''extension'''
        self.loss_c_sum = 0.0
        self.rho = 0.5

    def update_parameters(self, buffer, max_step, batch_size, repeat_times):
        policy_noise = 0.4  # standard deviation of policy noise
        update_freq = 2 ** 7  # delay update frequency, for soft target update
        self.act.eval()

        loss_a_sum = 0.0
        loss_c_sum = 0.0

        k = 1.0 + buffer.now_len / buffer.max_len
        batch_size_ = int(batch_size * k)
        update_times = int(max_step * k)

        for i in range(update_times * repeat_times):
            with torch.no_grad():
                reward, mask, state, action, next_state = buffer.random_sample(batch_size_, self.device)

                next_q_target, next_action = self.act_target.next__q_a(
                    state, next_state, policy_noise)
                q_target = reward + mask * next_q_target

            '''critic loss'''
            q_eval = self.act.critic(state, action)
            critic_loss = self.criterion(q_eval, q_target)
            loss_c_tmp = critic_loss.item()
            loss_c_sum += loss_c_tmp
            self.loss_c_sum += loss_c_tmp  # extension

            '''actor correction term'''
            actor_term = self.criterion(self.act(next_state), next_action)

            if i % repeat_times == 0:
                '''actor loss'''
                action_cur = self.act(state)  # policy gradient
                actor_loss = -self.act_target.critic(state, action_cur).mean()  # policy gradient
                loss_a_sum += actor_loss.item()

                united_loss = critic_loss + actor_term * (1 - self.rho) + actor_loss * (self.rho * 0.5)
            else:
                united_loss = critic_loss + actor_term * (1 - self.rho)

            """united loss"""
            self.act_optimizer.zero_grad()
            united_loss.backward()
            self.act_optimizer.step()

            self.update_counter += 1
            if self.update_counter == update_freq:
                self.update_counter = 0

                rho = np.exp(-(self.loss_c_sum / update_freq) ** 2)
                self.rho = (self.rho + rho) * 0.5
                self.loss_c_sum = 0.0

                if self.rho > 0.1:
                    self.act_target.load_state_dict(self.act.state_dict())

        loss_a_avg = loss_a_sum / update_times
        loss_c_avg = loss_c_sum / (update_times * repeat_times)
        return loss_a_avg, loss_c_avg

    def save_or_load_model(self, mod_dir, is_save):
        act_save_path = '{}/actor.pth'.format(mod_dir)
        # cri_save_path = '{}/critic.pth'.format(mod_dir)

        if is_save:
            torch.save(self.act.state_dict(), act_save_path)
            # torch.save(self.cri.state_dict(), cri_save_path)
            # print("Saved act and cri:", mod_dir)
        elif os.path.exists(act_save_path):
            act_dict = torch.load(act_save_path, map_location=lambda storage, loc: storage)
            self.act.load_state_dict(act_dict)
            self.act_target.load_state_dict(act_dict)
            # cri_dict = torch.load(cri_save_path, map_location=lambda storage, loc: storage)
            # self.cri.load_state_dict(cri_dict)
            # self.cri_target.load_state_dict(cri_dict)
        else:
            print("FileNotFound when load_model: {}".format(mod_dir))


class AgentTD3(AgentBasicAC):
    def __init__(self, state_dim, action_dim, net_dim):
        super(AgentBasicAC, self).__init__()
        self.learning_rate = 4e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        actor_dim = net_dim
        self.act = ActorDPG(state_dim, action_dim, actor_dim).to(self.device)
        self.act.train()
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=self.learning_rate * 0.5)

        self.act_target = ActorDPG(state_dim, action_dim, actor_dim).to(self.device)
        self.act_target.eval()
        self.act_target.load_state_dict(self.act.state_dict())

        critic_dim = int(net_dim * 1.25)
        self.cri = CriticTwin(state_dim, action_dim, critic_dim).to(self.device)
        self.cri.train()
        self.cri_optimizer = torch.optim.Adam(self.cri.parameters(), lr=self.learning_rate)

        self.cri_target = CriticTwin(state_dim, action_dim, critic_dim).to(self.device)
        self.cri_target.eval()
        self.cri_target.load_state_dict(self.cri.state_dict())

        self.criterion = nn.MSELoss()

        '''training record'''
        self.state = None  # env.reset()
        self.reward_sum = 0.0
        self.step_sum = 0
        self.update_counter = 0

    def update_parameters(self, buffer, max_step, batch_size, repeat_times):
        policy_noise = 0.2  # standard deviation of policy noise
        update_freq = 2 * repeat_times  # delay update frequency, for soft target update
        self.act.train()

        loss_a_sum = 0.0
        loss_c_sum = 0.0

        k = 1.0 + buffer.now_len / buffer.max_len
        batch_size_ = int(batch_size * k)
        update_times = int(max_step * k)

        for i in range(update_times * repeat_times):
            with torch.no_grad():
                reward, mask, state, action, next_s = buffer.random_sample(batch_size_, self.device)

                next_a = self.act_target(next_s, policy_noise)
                next_q_target = torch.min(*self.cri_target.get__q1_q2(next_s, next_a))  # TD3
                q_target = reward + mask * next_q_target

            '''critic_loss'''
            q_eval1, q_eval2 = self.cri.get__q1_q2(state, action)  # TD3
            critic_loss = self.criterion(q_eval1, q_target) + self.criterion(q_eval2, q_target)
            loss_c_sum += critic_loss.item() * 0.5  # TD3

            self.cri_optimizer.zero_grad()
            critic_loss.backward()
            self.cri_optimizer.step()

            '''actor_loss'''
            if i % repeat_times == 0:
                action_pg = self.act(state)  # policy gradient
                actor_loss = -self.cri(state, action_pg).mean()  # policy gradient
                loss_a_sum += actor_loss.item()

                self.act_optimizer.zero_grad()
                actor_loss.backward()
                self.act_optimizer.step()

            '''target update'''
            self.update_counter += 1
            if self.update_counter == update_freq:
                self.update_counter = 0
                self.soft_target_update(self.act_target, self.act)  # soft target update
                self.soft_target_update(self.cri_target, self.cri)  # soft target update

        loss_a_avg = loss_a_sum / update_times
        loss_c_avg = loss_c_sum / (update_times * repeat_times)
        return loss_a_avg, loss_c_avg


class AgentPPO:
    def __init__(self, state_dim, action_dim, net_dim):
        self.learning_rate = 4e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        self.act = ActorPPO(state_dim, action_dim, net_dim).to(self.device)
        self.act.train()
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=self.learning_rate * 0.5)  # betas=(0.5, 0.99))

        self.cri = CriticAdvantage(state_dim, net_dim).to(self.device)
        self.cri.train()
        self.cri_optimizer = torch.optim.Adam(self.cri.parameters(), lr=self.learning_rate)

        self.criterion = nn.SmoothL1Loss()

    def update_buffer_ppo(self, env, buffer, max_step, max_memo, max_action, gamma, state_norm):
        rewards = []
        steps = []

        step_counter = 0
        while step_counter < max_memo:
            state = env.reset()
            reward_sum = 0
            step_sum = 0

            state = state_norm(state)  # if state_norm:
            for step_sum in range(max_step):
                action, log_prob = self.select_actions((state,), explore_noise=True)
                action = action[0]
                log_prob = log_prob[0]

                next_state, reward, done, _ = env.step(action * max_action)
                reward_sum += reward

                next_state = state_norm(next_state)  # if state_norm:
                mask = 0 if done else gamma

                buffer.push(reward, mask, state, action, log_prob, )

                if done:
                    break
                state = next_state

            rewards.append(reward_sum)

            step_sum += 1
            steps.append(step_sum)
            step_counter += step_sum
        return rewards, steps

    def update_parameters_ppo(self, buffer, batch_size):  # todo cancel all_value
        clip = 0.25  # 0.5
        lambda_adv = 0.97
        lambda_entropy = 0.01
        repeat_times = 8
        self.act.train()

        loss_a_sum = 0.0
        loss_c_sum = 0.0

        all_batch = buffer.sample()
        max_memo = len(buffer)

        with torch.no_grad():
            all_reward = torch.tensor(all_batch.reward, dtype=torch.float32, device=self.device)
            all_mask = torch.tensor(all_batch.mask, dtype=torch.float32, device=self.device)
            all_state = torch.tensor(all_batch.state, dtype=torch.float32, device=self.device)
            all_value = self.cri(all_state)
            all_action = torch.tensor(all_batch.action, dtype=torch.float32, device=self.device)
            all_log_prob = torch.tensor(all_batch.log_prob, dtype=torch.float32, device=self.device)

        '''compute prev (value, return, advantage)'''
        # Generalization Advantage Estimate. ICLR. 2016. https://arxiv.org/pdf/1506.02438.pdf
        all_deltas = torch.empty(max_memo, dtype=torch.float32, device=self.device)
        all_returns = torch.empty(max_memo, dtype=torch.float32, device=self.device)
        all_advantages = torch.empty(max_memo, dtype=torch.float32, device=self.device)

        prev_return = 0
        prev_value = 0
        prev_advantage = 0
        for i in range(max_memo - 1, -1, -1):
            all_deltas[i] = all_reward[i] + prev_value * all_mask[i] - all_value[i]
            all_returns[i] = all_reward[i] + prev_return * all_mask[i]
            # ref: https://arxiv.org/pdf/1506.02438.pdf (generalization advantage estimate)
            all_advantages[i] = all_deltas[i] + lambda_adv * prev_advantage * all_mask[i]

            prev_return = all_returns[i]
            prev_value = all_value[i]
            prev_advantage = all_advantages[i]

        all_advantages = (all_advantages - all_advantages.mean()) / (all_advantages.std() + 1e-6)  # if advantage_norm:

        '''mini batch sample'''

        sample_times = int(repeat_times * max_memo / batch_size)
        for i_epoch in range(sample_times):
            '''random sample'''
            indices = rd.choice(max_memo, batch_size, replace=False)

            state = all_state[indices]
            action = all_action[indices]
            return_ = all_returns[indices]
            advantage = all_advantages[indices]
            old_log_prob = all_log_prob[indices]

            """Adaptive KL Penalty Coefficient
            loss_KLPEN = surrogate_obj + value_obj * loss_coeff_value + entropy_obj * lambda_entropy
            loss_KLPEN = (value_obj * loss_coeff_value)  (surrogate_obj + entropy_obj * lambda_entropy)
            loss_KLPEN = critic_loss + actor_loss
            """

            '''critic_loss'''
            new_values = self.cri(state).flatten()
            critic_loss = torch.mean((new_values - return_).pow(2)) / (return_.std() * 6)
            loss_c_sum += critic_loss.item()

            self.cri_optimizer.zero_grad()
            critic_loss.backward()
            self.cri_optimizer.step()

            '''actor_loss'''
            # surrogate objective of TRPO
            new_log_prob = self.act.get__log_prob(state, action)
            ratio = torch.exp(new_log_prob - old_log_prob)
            surrogate_obj0 = advantage * ratio
            surrogate_obj1 = advantage * ratio.clamp(1 - clip, 1 + clip)
            surrogate_obj = - torch.mean(torch.min(surrogate_obj0, surrogate_obj1))

            # policy entropy
            entropy_obj = torch.mean(torch.exp(new_log_prob) * new_log_prob)

            actor_loss = surrogate_obj + entropy_obj * lambda_entropy
            loss_a_sum += actor_loss.item()

            self.act_optimizer.zero_grad()
            actor_loss.backward()
            self.act_optimizer.step()

        loss_a_avg = loss_a_sum / sample_times
        loss_c_avg = loss_c_sum / sample_times
        return loss_a_avg, loss_c_avg

    def select_actions(self, states, explore_noise=0.0):  # CPU array to GPU tensor to CPU array
        states = torch.tensor(states, dtype=torch.float32, device=self.device)
        actions = self.act(states)

        if explore_noise == 0.0:
            actions = actions.cpu().data.numpy()
            return actions
        else:
            a_noise, log_prob = self.act.get__a__log_prob(actions)
            a_noise = a_noise.cpu().data.numpy()

            log_prob = log_prob.cpu().data.numpy()
            return a_noise, log_prob,

    def save_or_load_model(self, mod_dir, is_save):
        act_save_path = '{}/actor.pth'.format(mod_dir)
        # cri_save_path = '{}/critic.pth'.format(mod_dir)

        if is_save:
            torch.save(self.act.state_dict(), act_save_path)
            # torch.save(self.cri.state_dict(), cri_save_path)
            # print("Saved act and cri:", mod_dir)
        elif os.path.exists(act_save_path):
            act_dict = torch.load(act_save_path, map_location=lambda storage, loc: storage)
            self.act.load_state_dict(act_dict)
            # self.act_target.load_state_dict(act_dict)
            # cri_dict = torch.load(cri_save_path, map_location=lambda storage, loc: storage)
            # self.cri.load_state_dict(cri_dict)
            # self.cri_target.load_state_dict(cri_dict)
        else:
            print("FileNotFound when load_model: {}".format(mod_dir))


class AgentSAC(AgentBasicAC):  # todo
    def __init__(self, state_dim, action_dim, net_dim):
        super(AgentBasicAC, self).__init__()
        # use_densenet = False
        self.learning_rate = 2e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''network'''
        actor_dim = net_dim
        self.act = ActorSAC(state_dim, action_dim, actor_dim).to(self.device)
        self.act.train()
        self.act_optimizer = torch.optim.Adam(self.act.parameters(), lr=self.learning_rate)

        self.act_target = ActorSAC(state_dim, action_dim, net_dim).to(self.device)
        self.act_target.eval()
        self.act_target.load_state_dict(self.act.state_dict())

        critic_dim = int(net_dim * 1.25)
        self.cri = CriticTwin(state_dim, action_dim, critic_dim).to(self.device)
        self.cri.train()
        self.cri_optimizer = torch.optim.Adam(self.cri.parameters(), lr=self.learning_rate * 2)

        self.cri_target = CriticTwin(state_dim, action_dim, critic_dim).to(self.device)
        self.cri_target.eval()
        self.cri_target.load_state_dict(self.cri.state_dict())

        self.criterion = nn.MSELoss()

        '''training record'''
        self.state = None  # env.reset()
        self.reward_sum = 0.0
        self.step_sum = 0
        self.update_counter = 0

        '''extension: auto-alpha for maximum entropy'''
        self.log_alpha = torch.zeros(1, requires_grad=True, device=self.device)
        self.alpha = self.log_alpha.exp()
        self.alpha_optimizer = torch.optim.Adam((self.log_alpha,), lr=self.learning_rate)
        self.target_entropy = -1

    def update_parameters(self, buffer, max_step, batch_size, repeat_times):
        # policy_noise == (1.0 or True)  # stochastic policy choose noise_std by itself
        update_freq = 2 * repeat_times  # delay update frequency, for soft target update
        self.act.train()

        loss_a_sum = 0.0
        loss_c_sum = 0.0

        k = 1.0 + buffer.now_len / buffer.max_len
        batch_size_ = int(batch_size * k)
        update_times = int(max_step * k)

        for i in range(update_times * repeat_times):
            with torch.no_grad():
                reward, mask, state, action, next_s = buffer.random_sample(batch_size_, self.device)

                next_a_noise, next_log_prob = self.act_target.get__a__log_prob(next_s)
                next_q_target = torch.min(*self.cri_target.get__q1_q2(next_s, next_a_noise))  # CriticTwin
                next_q_target = next_q_target - next_log_prob * self.alpha  # SAC, alpha
                q_target = reward + mask * next_q_target
            '''critic_loss'''
            q1_value, q2_value = self.cri.get__q1_q2(state, action)  # CriticTwin
            critic_loss = self.criterion(q1_value, q_target) + self.criterion(q2_value, q_target)
            loss_c_sum += critic_loss.item() * 0.5  # CriticTwin

            self.cri_optimizer.zero_grad()
            critic_loss.backward()
            self.cri_optimizer.step()

            '''actor_loss'''
            if i % repeat_times == 0:
                # stochastic policy
                actions_noise, log_prob = self.act.get__a__log_prob(state, self.device)  # policy gradient
                # auto alpha
                alpha_loss = -(self.log_alpha * (self.target_entropy + log_prob).detach()).mean()
                self.alpha_optimizer.zero_grad()
                alpha_loss.backward()
                self.alpha_optimizer.step()

                # policy gradient
                self.alpha = self.log_alpha.exp()
                q_eval_pg = self.cri(state, actions_noise)  # policy gradient # todo
                actor_loss = (log_prob * self.alpha - q_eval_pg).mean()  # policy gradient
                loss_a_sum += actor_loss.item()

                self.act_optimizer.zero_grad()
                actor_loss.backward()
                self.act_optimizer.step()

            """target update"""
            self.update_counter += 1
            if self.update_counter == update_freq:
                self.update_counter = 0
                self.soft_target_update(self.act_target, self.act)  # soft target update
                self.soft_target_update(self.cri_target, self.cri)  # soft target update

        loss_a_avg = loss_a_sum / update_times
        loss_c_avg = loss_c_sum / (update_times * repeat_times)
        return loss_a_avg, loss_c_avg


class AgentDQN(AgentBasicAC):  # 2020-06-06 # todo
    def __init__(self, env, state_dim, action_dim, net_dim):  # 2020-04-30
        super(AgentBasicAC, self).__init__()
        self.learning_rate = 4e-4
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        '''dim and idx'''
        self.state_dim = state_dim
        self.action_dim = action_dim
        memo_action_dim = 1  # Discrete action space
        self.state_idx = 1 + 1 + state_dim  # reward_dim==1, done_dim==1
        self.action_idx = self.state_idx + memo_action_dim

        '''network'''
        actor_dim = net_dim
        act = QNetwork(state_dim, action_dim, actor_dim).to(self.device)
        act.train()
        self.act = act
        self.act_optimizer = torch.optim.Adam(act.parameters(), lr=learning_rate)

        act_target = QNetwork(state_dim, action_dim, actor_dim).to(self.device)
        act_target.eval()
        self.act_target = act_target
        self.act_target.load_state_dict(act.state_dict())

        self.criterion = nn.MSELoss()

        '''training record'''
        self.state = env.reset()
        self.reward_sum = 0.0
        self.step_sum = 0
        self.update_counter = 0

        '''extension: rho and loss_c'''
        self.explore_noise = 0.1
        self.policy_noise = 0.2

    def update_parameters(self, buffer, max_step, batch_size_, update_gap):
        loss_a_sum = 0.0
        loss_c_sum = 0.0

        k = 1.0 + buffer.now_len / buffer.max_len
        batch_size_ = int(batch_size_ * k)
        iter_step = int(max_step * k)

        for _ in range(iter_step):
            with torch.no_grad():
                rewards, masks, states, actions, next_states = buffer.random_sample(batch_size_, self.device)

                q_target = self.act_target(next_states).max(dim=1, keepdim=True)[0]
                q_target = rewards + masks * q_target

            self.act.train()
            actions = actions.type(torch.long)
            q_eval = self.act(states).gather(1, actions)
            critic_loss = self.criterion(q_eval, q_target)
            loss_c_sum += critic_loss.item()

            self.act_optimizer.zero_grad()
            critic_loss.backward()
            self.act_optimizer.step()

            self.update_counter += 1
            if self.update_counter == update_gap:
                self.update_counter = 0
                self.act_target.load_state_dict(self.act.state_dict())

        return loss_a_sum / iter_step, loss_c_sum / iter_step,

    def select_actions(self, states, explore_noise=0.0):  # state -> ndarray shape: (1, state_dim)
        states = torch.tensor(states, dtype=torch.float32, device=self.device)
        actions = self.act(states, explore_noise).argmax(dim=1).cpu().data.numpy()
        return actions

    def save_or_load_model(self, mod_dir, is_save):
        act_save_path = '{}/actor.pth'.format(mod_dir)

        if is_save:
            torch.save(self.act.state_dict(), act_save_path)
            # print("Saved neural network:", mod_dir)
        elif os.path.exists(act_save_path):
            act_dict = torch.load(act_save_path, map_location=lambda storage, loc: storage)
            self.act.load_state_dict(act_dict)
            self.act_target.load_state_dict(act_dict)
        else:
            print("FileNotFound when load_model: {}".format(mod_dir))


def initial_exploration(env, memo, max_step, action_max, reward_scale, gamma, action_dim):
    state = env.reset()

    rewards = list()
    reward_sum = 0.0
    steps = list()
    step = 0

    if isinstance(action_max, int) and action_max == int(1):
        def random_uniform_policy_for_discrete_action():
            return rd.randint(action_dim)

        get_random_action = random_uniform_policy_for_discrete_action
        action_max = int(1)
    else:
        def random_uniform_policy_for_continuous_action():
            return rd.uniform(-1, 1, size=action_dim)

        get_random_action = random_uniform_policy_for_continuous_action

    global_step = 0
    while global_step < max_step:
        # action = np.tanh(rd.normal(0, 0.25, size=action_dim))  # zero-mean gauss exploration
        action = get_random_action()
        next_state, reward, done, _ = env.step(action * action_max)
        reward_sum += reward
        step += 1

        adjust_reward = reward * reward_scale
        mask = 0.0 if done else gamma
        memo.add_memo((adjust_reward, mask, state, action, next_state))

        state = next_state
        if done:
            rewards.append(reward_sum)
            steps.append(step)
            global_step += step

            state = env.reset()  # reset the environment
            reward_sum = 0.0
            step = 1

    memo.init_before_sample()
    return rewards, steps


"""utils"""


class BufferListPPO:
    def __init__(self, ):
        self.storage = list()
        from collections import namedtuple
        self.transition = namedtuple(
            'Transition',
            # ('state', 'value', 'action', 'log_prob', 'mask', 'next_state', 'reward')
            # ('reward', 'mask', 'state', 'action', 'log_prob', 'value')
            ('reward', 'mask', 'state', 'action', 'log_prob',)
        )

    def push(self, *args):
        self.storage.append(self.transition(*args))

    def sample(self):
        return self.transition(*zip(*self.storage))

    def __len__(self):
        return len(self.storage)


class BufferList:
    def __init__(self, memo_max_len):
        self.memories = list()

        self.max_len = memo_max_len
        self.now_len = len(self.memories)

    def add_memo(self, memory_tuple):
        self.memories.append(memory_tuple)

    def init_after_add_memo(self):
        del_len = len(self.memories) - self.max_len
        if del_len > 0:
            del self.memories[:del_len]
            # print('Length of Deleted Memories:', del_len)

        self.now_len = len(self.memories)

    def random_sample(self, batch_size, device):
        # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # indices = rd.choice(self.memo_len, batch_size, replace=False)  # why perform worse?
        # indices = rd.choice(self.memo_len, batch_size, replace=True)  # why perform better?
        # same as:
        indices = rd.randint(self.now_len, size=batch_size)

        '''convert list into array'''
        arrays = [list()
                  for _ in range(5)]  # len(self.memories[0]) == 5
        for index in indices:
            items = self.memories[index]
            for item, array in zip(items, arrays):
                array.append(item)

        '''convert array into torch.tensor'''
        tensors = [torch.tensor(np.array(ary), dtype=torch.float32, device=device)
                   for ary in arrays]
        return tensors


class BufferTuple:  # todo plan for PPO
    def __init__(self, memo_max_len):
        self.memories = list()

        self.max_len = memo_max_len
        self.now_len = None  # init in init_after_add_memo()

        from collections import namedtuple
        self.transition = namedtuple(
            'Transition', ('reward', 'mask', 'state', 'action', 'next_state',)
        )

    def add_memo(self, args):
        self.memories.append(self.transition(*args))

    def init_after_add_memo(self):
        del_len = len(self.memories) - self.max_len
        if del_len > 0:
            del self.memories[:del_len]
            # print('Length of Deleted Memories:', del_len)

        self.now_len = len(self.memories)

    def random_sample(self, batch_size, device):
        # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # indices = rd.choice(self.memo_len, batch_size, replace=False)  # why perform worse?
        # indices = rd.choice(self.memo_len, batch_size, replace=True)  # why perform better?
        # same as:
        indices = rd.randint(self.now_len, size=batch_size)

        '''convert tuple into array'''
        arrays = self.transition(*zip(*[self.memories[i] for i in indices]))

        '''convert array into torch.tensor'''
        tensors = [torch.tensor(np.array(ary), dtype=torch.float32, device=device)
                   for ary in arrays]
        return tensors


class BufferArray:  # 2020-05-20
    def __init__(self, memo_max_len, state_dim, action_dim, ):
        memo_dim = 1 + 1 + state_dim + action_dim + state_dim
        self.memories = np.empty((memo_max_len, memo_dim), dtype=np.float32)

        self.next_idx = 0
        self.is_full = False
        self.max_len = memo_max_len
        self.now_len = self.max_len if self.is_full else self.next_idx

        self.state_idx = 1 + 1 + state_dim  # reward_dim==1, done_dim==1
        self.action_idx = self.state_idx + action_dim

    def add_memo(self, memo_tuple):
        self.memories[self.next_idx] = np.hstack(memo_tuple)
        self.next_idx = self.next_idx + 1
        if self.next_idx >= self.max_len:
            self.is_full = True
            self.next_idx = 0

    def extend_memo(self, memo_array):  # 2019-12-12
        size = memo_array.shape[0]
        next_idx = self.next_idx + size
        if next_idx < self.max_len:
            self.memories[self.next_idx:next_idx] = memo_array
        if next_idx >= self.max_len:
            if next_idx > self.max_len:
                self.memories[self.next_idx:self.max_len] = memo_array[:self.max_len - self.next_idx]
            self.is_full = True
            next_idx = next_idx - self.max_len
            self.memories[0:next_idx] = memo_array[-next_idx:]
        else:
            self.memories[self.next_idx:next_idx] = memo_array
        self.next_idx = next_idx

    def init_before_sample(self):
        self.now_len = self.max_len if self.is_full else self.next_idx

    def random_sample(self, batch_size, device):
        # device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # indices = rd.choice(self.memo_len, batch_size, replace=False)  # why perform worse?
        # indices = rd.choice(self.memo_len, batch_size, replace=True)  # why perform better?
        # same as:
        indices = rd.randint(self.now_len, size=batch_size)
        memory = self.memories[indices]
        if device:
            memory = torch.tensor(memory, device=device)

        '''convert array into torch.tensor'''
        tensors = (
            memory[:, 0:1],  # rewards
            memory[:, 1:2],  # masks, mark == (1-float(done)) * gamma
            memory[:, 2:self.state_idx],  # states
            memory[:, self.state_idx:self.action_idx],  # actions
            memory[:, self.action_idx:],  # next_states
        )
        return tensors


class Recorder:
    def __init__(self, agent, max_step, max_action, target_reward,
                 env_name, eva_size=100, show_gap=2 ** 7, smooth_kernel=2 ** 4,
                 state_norm=None, **_kwargs):
        self.show_gap = show_gap
        self.smooth_kernel = smooth_kernel

        '''get_eva_reward(agent, env_list, max_step, max_action)'''
        self.agent = agent
        self.env_list = [gym.make(env_name) for _ in range(eva_size)]
        self.max_step = max_step
        self.max_action = max_action
        self.e1 = 3
        self.e2 = int(eva_size // np.e)
        self.running_stat = state_norm

        '''reward'''
        self.rewards = get_eva_reward(agent, self.env_list[:5], max_step, max_action, self.running_stat)
        self.reward_avg = np.average(self.rewards)
        self.reward_std = float(np.std(self.rewards))
        self.reward_target = target_reward
        self.reward_max = self.reward_avg

        self.record_epoch = list()  # record_epoch.append((epoch_reward, actor_loss, critic_loss, iter_num))
        self.record_eval = [(0, self.reward_avg, self.reward_std), ]  # [(epoch, reward_avg, reward_std), ]
        self.total_step = 0

        self.epoch = 0
        self.train_time = 0  # train_time
        self.train_timer = timer()  # train_time
        self.start_time = self.show_time = timer()
        print("epoch|   reward   r_max    r_ave    r_std |  loss_A loss_C |step")

    def show_reward(self, epoch_rewards, iter_numbers, loss_a, loss_c):
        self.train_time += timer() - self.train_timer  # train_time
        self.epoch += len(epoch_rewards)

        if isinstance(epoch_rewards, float):
            epoch_rewards = (epoch_rewards,)
            iter_numbers = (iter_numbers,)
        for reward, iter_num in zip(epoch_rewards, iter_numbers):
            self.record_epoch.append((reward, loss_a, loss_c, iter_num))
            self.total_step += iter_num

        if timer() - self.show_time > self.show_gap:
            self.rewards = get_eva_reward(self.agent, self.env_list[:self.e1], self.max_step, self.max_action,
                                          self.running_stat)
            self.reward_avg = np.average(self.rewards)
            self.reward_std = float(np.std(self.rewards))
            self.record_eval.append((len(self.record_epoch), self.reward_avg, self.reward_std))

            slice_reward = np.array(self.record_epoch[-self.smooth_kernel:])[:, 0]
            smooth_reward = np.average(slice_reward, axis=0)
            print("{:4} |{:8.2f} {:8.2f} {:8.2f} {:8.2f} |{:8.2f} {:6.2f} |{:.2e}".format(
                len(self.record_epoch),
                smooth_reward, self.reward_max, self.reward_avg, self.reward_std,
                loss_a, loss_c, self.total_step))

            self.show_time = timer()  # reset show_time after get_eva_reward_batch !
        else:
            self.rewards = list()

    def check_reward(self, cwd, loss_a, loss_c):  # 2020-05-05
        is_solved = False
        if self.reward_avg >= self.reward_max:  # and len(self.rewards) > 1:  # 2020-04-30
            self.rewards.extend(get_eva_reward(self.agent, self.env_list[:self.e2], self.max_step, self.max_action,
                                               self.running_stat))
            self.reward_avg = np.average(self.rewards)

            if self.reward_avg >= self.reward_max:
                self.reward_max = self.reward_avg

                '''NOTICE! Recorder saves the agent with max reward automatically. '''
                self.agent.save_or_load_model(cwd, is_save=True)

                if self.reward_max >= self.reward_target:
                    res_env_len = len(self.env_list) - len(self.rewards)
                    self.rewards.extend(get_eva_reward(
                        self.agent, self.env_list[:res_env_len], self.max_step, self.max_action,
                        self.running_stat))
                    self.reward_avg = np.average(self.rewards)
                    self.reward_max = self.reward_avg

                    if self.reward_max >= self.reward_target:
                        print("########## Solved! ###########")
                        is_solved = True

            self.reward_std = float(np.std(self.rewards))
            self.record_eval[-1] = (len(self.record_epoch), self.reward_avg, self.reward_std)  # refresh
            print("{:4} |{:8} {:8.2f} {:8.2f} {:8.2f} |{:8.2f} {:6.2f} |{:.2e}".format(
                len(self.record_epoch),
                '', self.reward_max, self.reward_avg, self.reward_std,
                loss_a, loss_c, self.total_step, ))

        self.train_timer = timer()  # train_time
        return is_solved

    def print_and_save_npy(self, env_name, cwd):  # 2020-04-30
        iter_used = self.total_step  # int(sum(np.array(self.record_epoch)[:, -1]))
        time_used = int(timer() - self.start_time)
        print('Used Time:', time_used)
        self.train_time = int(self.train_time)  # train_time
        print('TrainTime:', self.train_time)  # train_time

        print_str = "{}-{:.2f}AVE-{:.2f}STD-{}E-{}S-{}T".format(
            env_name, self.reward_max, self.reward_std, self.epoch, self.train_time, iter_used)  # train_time
        print(print_str)
        nod_path = '{}/{}.txt'.format(cwd, print_str)
        os.mknod(nod_path, ) if not os.path.exists(nod_path) else None

        np.save('%s/record_epoch.npy' % cwd, self.record_epoch)
        np.save('%s/record_eval.npy' % cwd, self.record_eval)
        print("Saved record_*.npy in:", cwd)

        return self.train_time


class RewardNormalization:
    def __init__(self, n_max, n_min, size=2 ** 7):
        self.k = size / (n_max - n_min)
        # print(';;RewardNorm', n_max, n_min)
        # print(';;RewardNorm', self(n_max), self(n_min))

    def __call__(self, n):
        return n * self.k


class RunningStat:  # for class AutoNormalization
    def __init__(self, shape):
        self._n = 0
        self._M = np.zeros(shape)
        self._S = np.zeros(shape)

    def push(self, x):
        x = np.asarray(x)
        # assert x.shape == self._M.shape
        self._n += 1
        if self._n == 1:
            self._M[...] = x
        else:
            pre_memo = self._M.copy()
            self._M[...] = pre_memo + (x - pre_memo) / self._n
            self._S[...] = self._S + (x - pre_memo) * (x - self._M)

            self._n = min(self._n, 1e6)  # todo

    @property
    def n(self):
        return self._n

    @property
    def mean(self):
        return self._M

    @property
    def var(self):
        return self._S / (self._n - 1) if self._n > 1 else np.square(self._M)

    @property
    def std(self):
        return np.sqrt(self.var)

    @property
    def shape(self):
        return self._M.shape


class AutoNormalization:
    def __init__(self, shape, demean=True, destd=True, clip=6.0):
        self.demean = demean
        self.destd = destd
        self.clip = clip

        self.rs = RunningStat(shape)

    def __call__(self, x, update=True):
        if update:
            self.rs.push(x)
        if self.demean:
            x = x - self.rs.mean
        if self.destd:
            x = x / (self.rs.std + 1e-8)
        if self.clip:
            x = np.clip(x, -self.clip, self.clip)
        return x


class OrnsteinUhlenbeckProcess:
    def __init__(self, size, theta=0.15, sigma=0.3, x0=0.0, dt=1e-2):
        """
        Source: https://github.com/slowbull/DDPG/blob/master/src/explorationnoise.py
        I think that:
        It makes Zero-mean Gaussian Noise more stable.
        It helps agent explore better in a inertial system.
        """
        self.theta = theta
        self.sigma = sigma
        self.x0 = x0
        self.dt = dt
        self.size = size

    def __call__(self):
        noise = self.sigma * np.sqrt(self.dt) * rd.normal(size=self.size)
        x = self.x0 - self.theta * self.x0 * self.dt + noise
        self.x0 = x  # update x0
        return x


def get_eva_reward(agent, env_list, max_step, max_action, running_state=None):  # class Recorder 2020-01-11
    """max_action can be None for Discrete action space"""
    act = agent.act
    act.eval()

    env_list_copy = env_list.copy()
    eva_size = len(env_list_copy)

    sum_rewards = [0.0, ] * eva_size
    states = [env.reset() for env in env_list_copy]

    reward_sums = list()
    for iter_num in range(max_step):
        if running_state:
            states = [running_state(state, update=False) for state in states]  # if state_norm:
        actions = agent.select_actions(states)

        next_states = list()
        done_list = list()
        if max_action:  # Continuous action space
            actions *= max_action
        for i in range(len(env_list_copy) - 1, -1, -1):
            next_state, reward, done, _ = env_list_copy[i].step(actions[i])

            next_states.insert(0, next_state)
            sum_rewards[i] += reward
            done_list.insert(0, done)
            if done:
                reward_sums.append(sum_rewards[i])
                del sum_rewards[i]
                del env_list_copy[i]
        states = next_states

        if len(env_list_copy) == 0:
            break
    else:
        reward_sums.extend(sum_rewards)
    act.train()

    return reward_sums
