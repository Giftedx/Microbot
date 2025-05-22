import os
import time
from custom_env import CustomGameEnv
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.vec_env import DummyVecEnv

# Create directories for logs and models
log_dir = "sb3_logs/"
model_dir = "sb3_models/"
os.makedirs(log_dir, exist_ok=True)
os.makedirs(model_dir, exist_ok=True)

if __name__ == '__main__':
    print("Initializing environment...")
    # It's often good to wrap the custom environment in DummyVecEnv for SB3
    env = DummyVecEnv([lambda: CustomGameEnv(render_mode='human')])
    
    # It's recommended to check your custom environment before training
    # print("Checking environment...")
    # check_env(env.envs[0], warn=True) # Check the underlying CustomGameEnv instance
    # Note: check_env might have issues with complex observation spaces or network comms
    # during checks. Use with caution or skip if it causes problems for this specific env.

    print("Initializing PPO agent...")
    # The policy should match the observation space. 'MultiInputPolicy' is used for Dict spaces.
    model = PPO("MultiInputPolicy", env, verbose=1, tensorboard_log=log_dir)

    # Training parameters
    total_timesteps_train = 1000 # Short training for testing setup
    save_interval = 500       # Save model every N timesteps
    model_save_path_base = os.path.join(model_dir, f"ppo_custom_game_model_{int(time.time())}")

    print(f"Starting training for {total_timesteps_train} timesteps...")
    try:
        for i in range(total_timesteps_train // save_interval):
            model.learn(total_timesteps=save_interval, reset_num_timesteps=False, tb_log_name="PPO")
            model.save(f"{model_save_path_base}_{i * save_interval}")
            print(f"Model saved at timestep {i * save_interval}")
        
        remaining_timesteps = total_timesteps_train % save_interval
        if remaining_timesteps > 0:
            model.learn(total_timesteps=remaining_timesteps, reset_num_timesteps=False, tb_log_name="PPO")
            model.save(f"{model_save_path_base}_final")
        
        print(f"Training finished. Model saved as {model_save_path_base}_final.zip")
        print(f"To view tensorboard logs, run: tensorboard --logdir {log_dir}")

    except Exception as e:
        print(f"An error occurred during training: {e}")
    finally:
        print("Closing environment...")
        env.close() # Important to close the environment and thus the ZMQ client

    # Example of loading and running the trained model (optional)
    # print("Loading trained model...")
    # loaded_model = PPO.load(f"{model_save_path_base}_final.zip")
    # obs = env.reset()
    # for _ in range(100):
    #     action, _states = loaded_model.predict(obs, deterministic=True)
    #     obs, rewards, dones, info = env.step(action)
    #     env.render() # If you want to see the agent play
    #     if dones.any(): # dones is a list/array in VecEnv
    #         obs = env.reset()
    #         break 
    # env.close()
