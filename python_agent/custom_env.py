import gymnasium as gym
from gymnasium import spaces
import numpy as np
import json
import time # Keep if used in __main__

from zmq_client import ZMQClient

MAX_NEARBY_NPCS = 3
MAX_INVENTORY_ITEMS = 5
MAX_GROUND_ITEMS = 5 # New constant
BONE_ITEM_ID = 526 # Example ID for Bones

class CustomGameEnv(gym.Env):
    metadata = {'render_modes': ['human', 'rgb_array'], 'render_fps': 4}

    def __init__(self, render_mode=None):
        super().__init__()
        self.client = ZMQClient()

        # 0:type, 1:attack_goblin, 2:interact_door, 3:walk_lumbridge, 4:noop, 5:pickup_bone
        # New: 6: invoke_menu_action_detailed (example: click first inventory slot)
        self.action_space = spaces.Discrete(7) 

        self.observation_space = spaces.Dict({
            "player_stats": spaces.Box(low=0, high=np.array([200, 200, 200, 200, 1.0]), dtype=np.float32),
            "player_location": spaces.Box(low=-np.inf, high=np.inf, shape=(3,), dtype=np.float32),
            "nearby_npcs_info": spaces.Box(low=-1, high=np.inf, shape=(MAX_NEARBY_NPCS, 4), dtype=np.float32), # id, x, y, anim
            "inventory_item_ids": spaces.Box(low=-1, high=np.inf, shape=(MAX_INVENTORY_ITEMS,), dtype=np.float32), # id
            "nearby_ground_items_info": spaces.Box(low=-1, high=np.inf, shape=(MAX_GROUND_ITEMS, 4), dtype=np.float32), # id, quantity, x, y
        })
        
        self._current_game_info = {} # Initialize to ensure it exists
        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode


    def _get_obs(self):
        raw_obs_data = self.client.get_observation()
        
        obs = {
            "player_stats": np.zeros(self.observation_space["player_stats"].shape, dtype=np.float32),
            "player_location": np.zeros(self.observation_space["player_location"].shape, dtype=np.float32),
            "nearby_npcs_info": np.full(self.observation_space["nearby_npcs_info"].shape, -1.0, dtype=np.float32),
            "inventory_item_ids": np.full(self.observation_space["inventory_item_ids"].shape, -1.0, dtype=np.float32),
            "nearby_ground_items_info": np.full(self.observation_space["nearby_ground_items_info"].shape, -1.0, dtype=np.float32),
        }
        # Initialize parts of the info dictionary that will be populated here
        self._current_game_info = {
            "raw_observation": raw_obs_data, # Store raw for debugging
            "npc_names": [""] * MAX_NEARBY_NPCS,
            "inventory_item_names": [""] * MAX_INVENTORY_ITEMS,
            "ground_item_names": [""] * MAX_GROUND_ITEMS
        }

        if not raw_obs_data or raw_obs_data.get("status") == "error":
            error_msg = "Unknown error or no data received"
            if raw_obs_data and 'message' in raw_obs_data:
                error_msg = raw_obs_data['message']
            print(f"Warning: Error or no data in received observation: {error_msg}. Using default observation.")
            # self._current_game_info will still contain the raw_obs_data if it exists
            return obs # Return the default initialized obs

        try:
            # Player Stats
            obs["player_stats"][0] = float(raw_obs_data.get("player_current_health", 0))
            obs["player_stats"][1] = float(raw_obs_data.get("player_max_health", 0))
            obs["player_stats"][2] = float(raw_obs_data.get("player_current_prayer", 0))
            obs["player_stats"][3] = float(raw_obs_data.get("player_max_prayer", 0))
            obs["player_stats"][4] = float(raw_obs_data.get("player_run_energy_percentage", 0.0))

            # Player Location
            player_loc_data = raw_obs_data.get("player_location", {}) # Default to empty dict if null
            if player_loc_data: # Check if player_loc_data is not None and not empty
                obs["player_location"][0] = float(player_loc_data.get("x", 0))
                obs["player_location"][1] = float(player_loc_data.get("y", 0))
                obs["player_location"][2] = float(player_loc_data.get("plane", 0))
            else: # Fill with default if player_location was null or empty
                obs["player_location"][:] = 0.0

            # Nearby NPCs - now includes animation ID
            nearby_npcs_data = raw_obs_data.get("nearby_npcs", [])
            for i in range(min(len(nearby_npcs_data), MAX_NEARBY_NPCS)):
                npc = nearby_npcs_data[i]
                if isinstance(npc, dict):
                    obs["nearby_npcs_info"][i, 0] = float(npc.get("id", -1))
                    npc_loc = npc.get("location", {})
                    if isinstance(npc_loc, dict):
                        obs["nearby_npcs_info"][i, 1] = float(npc_loc.get("x", -1))
                        obs["nearby_npcs_info"][i, 2] = float(npc_loc.get("y", -1))
                    obs["nearby_npcs_info"][i, 3] = float(npc.get("animation", -1)) # New: animation ID
                    self._current_game_info["npc_names"][i] = npc.get("name", "Unknown")
                else:
                    print(f"Warning: NPC data at index {i} is not a dictionary: {npc}")
            
            # Inventory Items - now includes names in info
            inventory_data = raw_obs_data.get("inventory", [])
            for i in range(min(len(inventory_data), MAX_INVENTORY_ITEMS)):
                item = inventory_data[i]
                if isinstance(item, dict):
                    obs["inventory_item_ids"][i] = float(item.get("id", -1))
                    self._current_game_info["inventory_item_names"][i] = item.get("name", "Unknown")
                else:
                    print(f"Warning: Inventory item data at index {i} is not a dictionary: {item}")

            # Nearby Ground Items - now includes names in info
            ground_items_data = raw_obs_data.get("nearby_ground_items", [])
            for i in range(min(len(ground_items_data), MAX_GROUND_ITEMS)):
                g_item = ground_items_data[i]
                if isinstance(g_item, dict):
                    obs["nearby_ground_items_info"][i, 0] = float(g_item.get("id", -1))
                    obs["nearby_ground_items_info"][i, 1] = float(g_item.get("quantity", 0))
                    g_item_loc = g_item.get("location", {})
                    if isinstance(g_item_loc, dict):
                        obs["nearby_ground_items_info"][i, 2] = float(g_item_loc.get("x", -1))
                        obs["nearby_ground_items_info"][i, 3] = float(g_item_loc.get("y", -1))
                    self._current_game_info["ground_item_names"][i] = g_item.get("name", "Unknown")
                else:
                    print(f"Warning: Ground item data at index {i} is not a dictionary: {g_item}")
        
        except (TypeError, ValueError) as e:
            print(f"Warning: Type or value error while processing observation data: {e}. Raw data: {raw_obs_data}. Using partially processed/default observation.")
        except Exception as e:
            print(f"Warning: Unexpected error while processing observation data: {e}. Raw data: {raw_obs_data}. Using partially processed/default observation.")
            
        return obs

    def _get_info(self):
        # self._current_game_info is populated by _get_obs()
        # It contains raw_observation and parsed names.
        return self._current_game_info


    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        # For now, reset doesn't do much with the game, just gets an observation
        # In a real scenario, this might trigger a game reset action via ZMQ
        print("Environment reset.")
        self.last_observation = self._get_obs() # Initial observation
        info = self._get_info()
        return self.last_observation, info

    def step(self, action):
        action_type = None
        parameters = {}
        reward = -0.1 # Small cost for taking any action (encourages efficiency)
        terminated = False 
        
        bones_visible_in_last_obs = False # Default for action 5 reward logic

        if action == 0: # type_string
            action_type = "type_string"
            parameters = {"text": "Hello AI from Gym Env"}
        elif action == 1: # attack_npc (e.g., Goblin ID 1610)
            action_type = "attack_npc"
            parameters = {"npc_id": 1610} 
        elif action == 2: # interact_object (e.g., a Door ID 16465)
            action_type = "interact_object"
            parameters = {"object_id": 16465, "action": "Open"}
        elif action == 3: # walk_to (e.g., Lumbridge center)
            action_type = "walk_to"
            parameters = {"x": 3222, "y": 3222, "plane": 0}
        elif action == 4: # noop
            action_type = None 
            reward = 0.0 # No penalty for no-op, or small positive if desired
        elif action == 5: # pickup_bone
            action_type = "interact_ground_item"
            parameters = {"item_id": BONE_ITEM_ID}
            
            if hasattr(self, 'last_observation') and self.last_observation:
                for i in range(MAX_GROUND_ITEMS):
                    if self.last_observation["nearby_ground_items_info"][i, 0] == BONE_ITEM_ID:
                        bones_visible_in_last_obs = True
                        # Example of targeting specific bone if API supported it and it was desired:
                        # parameters["x"] = int(self.last_observation["nearby_ground_items_info"][i, 2])
                        # parameters["y"] = int(self.last_observation["nearby_ground_items_info"][i, 3])
                        # parameters["plane"] = int(self.last_observation["player_location"][2])
                        break
            
            if bones_visible_in_last_obs:
                print(f"Env Action: Attempting to pick up Bone (ID: {BONE_ITEM_ID}) based on last observation.")
            else:
                print(f"Env Action: Pick up Bone chosen, but no bones were noted in last observation.")
                action_type = None 
                reward = -1.0 
        
        elif action == 6: # invoke_menu_action_detailed (Example: Click first inventory slot)
            action_type = "invoke_menu_action_detailed"
            widget_inventory_packed_id = (149 << 16) | 0 
            
            parameters = {
                "option": "Use", 
                "target": "", # Typically item name, but can be empty for some slot actions
                "id": -1,     # Often item ID in slot, or -1 if not applicable to action/widget
                "opcode": 57, # MenuAction.CC_OP (57)
                "param0": 0,  # Slot index
                "param1": widget_inventory_packed_id, 
                "force_left_click": True 
            }
            print(f"Env Action: Detailed menu invocation on first inventory slot (example).")

        else:
            print(f"Unknown action discrete value: {action}")
            action_type = None
            reward = -1.0
        
        action_status = {"status": "no_action_taken"}
        if action_type:
            action_status = self.client.execute_action(action_type, parameters)
            print(f"Action result from server: {action_status}")
            if action_status and action_status.get("status") == "submitted":
                if action == 5 and bones_visible_in_last_obs: 
                    reward += 10.0 
                elif action == 5 and not bones_visible_in_last_obs: 
                     pass 
                else: 
                    reward += 0.1 
            else: 
                if action_type : 
                     reward -= 0.5
        
        self.last_observation = self._get_obs() 
        info = self._get_info() 
        info["action_status"] = action_status

        # Example termination condition (e.g., if player health drops to 0)
        # current_health = observation["player_stats"][0] # Accessing from Dict observation
        # if current_health <= 0:
        #    terminated = True
        #    reward = -100 # Large penalty for dying

        # For now, episodes don't terminate based on game state in this basic setup
        truncated = False 
        return observation, reward, terminated, truncated, info

    def render(self):
        if self.render_mode == "human":
            # Potentially print some state to console or use a simple visualizer
            # obs_data = self._get_info().get("raw_observation", {}) # _get_info() returns the dict directly now
            obs_dict = self._get_obs() # Get the processed observation dictionary
            print(f"--- Current State (Render) ---")
            for key, value in obs_dict.items():
                if isinstance(value, np.ndarray):
                    print(f"  {key}: {value.tolist()}") # Convert numpy arrays to lists for cleaner printing
                else:
                    print(f"  {key}: {value}")
            print(f"------------------------------")

        elif self.render_mode == "rgb_array":
            # This would require getting screen pixels from the Java side via ZMQ
            # For now, return a dummy black image
            return np.zeros((100, 100, 3), dtype=np.uint8)


    def close(self):
        self.client.close()
        print("CustomGameEnv closed.")

if __name__ == '__main__':
    # Example usage:
    env = CustomGameEnv(render_mode='human')
    
    # Test reset
    obs, info = env.reset()
    env.render()
    
    # Test a few steps
    for i in range(7): # Test all 7 actions
        action = i 
        print(f"\n--- Step {i+1}, Taking Action: {action} ---")
        obs, reward, terminated, truncated, info = env.step(action)
        env.render() # Render the observation
        print(f"Reward: {reward}, Terminated: {terminated}, Truncated: {truncated}")
        print(f"Info: {info}") # Contains raw observation and action status
        if terminated or truncated:
            print("Episode finished.")
            break
        time.sleep(1) # Small delay to see output and allow server to process

    env.close()
