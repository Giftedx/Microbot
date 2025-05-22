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

# --- Task-Specific Constants for Simple Combat Agent ---
GOBLIN_NPC_ID = 125  # Example ID for a common Goblin
FOOD_ITEM_IDS = [315, 2140, 2309]  # Cooked Shrimp, Cooked Chicken, Bread
EAT_HEALTH_THRESHOLD_PERCENTAGE = 0.6 # Eat if health is <= 60% of max health
# Example waypoints near Lumbridge Goblins (east of river, south of castle)
GOBLIN_AREA_WAYPOINTS = [
    (3248, 3237, 0), # Approximate
    (3252, 3230, 0), # Approximate
    (3245, 3224, 0)  # Approximate
]
# --- End Task-Specific Constants ---

# Define known combat animations (example IDs, replace with actual ones)
PLAYER_COMBAT_ANIMATION_IDS = [422, 423, 390, 393, 386, 80, 819, 1658] # Common melee/ranged/magic attack animations

class CustomGameEnv(gym.Env):
    metadata = {'render_modes': ['human', 'rgb_array'], 'render_fps': 4}

    def __init__(self, render_mode=None):
        super().__init__()
        self.client = ZMQClient()

        # Action Space: 0:ATTACK_NPC, 1:EAT_FOOD, 2:MOVE_TO_GOBLIN_AREA, 3:NOOP
        self.action_space = spaces.Discrete(4) 

        self.observation_space = spaces.Dict({ 
            "player_stats": spaces.Box(low=0, high=np.array([200, 200, 200, 200, 1.0]), dtype=np.float32), # cur_hp,max_hp,cur_pray,max_pray,run_energy
            "player_location": spaces.Box(low=-np.inf, high=np.inf, shape=(3,), dtype=np.float32), # x,y,plane
            "nearby_npcs_info": spaces.Box(low=-1, high=np.inf, shape=(MAX_NEARBY_NPCS, 4), dtype=np.float32), # id,x,y,anim
            "inventory_item_ids": spaces.Box(low=-1, high=np.inf, shape=(MAX_INVENTORY_ITEMS,), dtype=np.float32), # id
            "nearby_ground_items_info": spaces.Box(low=-1, high=np.inf, shape=(MAX_GROUND_ITEMS, 4), dtype=np.float32),#id,q,x,y
            "player_animation": spaces.Box(low=-1, high=np.inf, shape=(1,), dtype=np.int32) # New player animation ID
        })
        
        self._current_game_info = {} 
        self.last_observation = None 
        
        self.current_target_npc_id = None 
        self.waypoint_index = 0
        self._update_combat_state_from_obs(None) # Initialize combat state

        assert render_mode is None or render_mode in self.metadata["render_modes"]
        self.render_mode = render_mode


    def _get_obs(self):
        raw_obs_data = self.client.get_observation()
        
        obs = {
            "player_stats": np.zeros(self.observation_space["player_stats"].shape, dtype=np.float32),
            "player_location": np.full(self.observation_space["player_location"].shape, 0.0, dtype=np.float32),
            "nearby_npcs_info": np.full(self.observation_space["nearby_npcs_info"].shape, -1.0, dtype=np.float32),
            "inventory_item_ids": np.full(self.observation_space["inventory_item_ids"].shape, -1.0, dtype=np.float32),
            "nearby_ground_items_info": np.full(self.observation_space["nearby_ground_items_info"].shape, -1.0, dtype=np.float32),
            "player_animation": np.full(self.observation_space["player_animation"].shape, -1, dtype=np.int32) # New
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
            obs["player_animation"][0] = int(raw_obs_data.get("player_animation", -1)) # New

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
            # Ensure player_animation also has a default if error occurs mid-parse
            obs["player_animation"][0] = -1
        except Exception as e:
            print(f"Warning: Unexpected error while processing observation data: {e}. Raw data: {raw_obs_data}. Using partially processed/default observation.")
            obs["player_animation"][0] = -1
            
        return obs

    def _get_info(self):
        # self._current_game_info is populated by _get_obs()
        # It contains raw_observation and parsed names.
        return self._current_game_info


    def _update_combat_state_from_obs(self, current_observation):
        if current_observation and current_observation.get("player_animation") is not None:
            current_player_anim = current_observation["player_animation"][0]
            self.player_is_in_combat_animation = current_player_anim in PLAYER_COMBAT_ANIMATION_IDS
            # Could also update self.current_target_npc_id here if player is targeting an NPC
            # For example, if player_is_interacting_with_npc_id is part of observation
        else:
            self.player_is_in_combat_animation = False

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        print("Environment reset.")
        initial_observation = self._get_obs() 
        self._update_combat_state_from_obs(initial_observation) # Call the new method
        self.last_observation = initial_observation
        info = self._get_info() 
        return initial_observation, info

    def step(self, action):
        base_action_cost = -0.1 # Default cost for taking a step
        action_type = None
        parameters = {}
        action_specific_reward_info = {} # To pass data to reward function

        # --- Action Selection and Parameter Generation ---
        if action == 0: # ATTACK_NPC
            action_type, parameters, action_specific_reward_info = self._handle_attack_npc(self.last_observation)
        elif action == 1: # EAT_FOOD
            action_type, parameters, action_specific_reward_info = self._handle_eat_food(self.last_observation)
        elif action == 2: # MOVE_TO_GOBLIN_AREA
            action_type = "walk_to" # This one is simpler, can define params directly or use a helper
            selected_waypoint = GOBLIN_AREA_WAYPOINTS[self.waypoint_index % len(GOBLIN_AREA_WAYPOINTS)]
            parameters = {"x": selected_waypoint[0], "y": selected_waypoint[1], "plane": selected_waypoint[2]}
            self.waypoint_index += 1
            action_specific_reward_info = {"action_taken": "move_to_waypoint"}
            print(f"Env Action: Move to waypoint {selected_waypoint}")
        elif action == 3: # NOOP
            action_type = None # No action sent to game
            action_specific_reward_info = {"action_taken": "noop"}
            print(f"Env Action: NOOP")
        else:
            print(f"Unknown action discrete value: {action}")
            action_specific_reward_info = {"action_taken": "unknown"}
        
        # --- Execute Action via ZMQ ---
        action_status = {"status": "no_action_taken"}
        if action_type:
            action_status = self.client.execute_action(action_type, parameters)
            print(f"Action result from server: {action_status}")
        
        # --- Get New Observation and Info ---
        current_observation = self._get_obs() 
        self._update_combat_state_from_obs(current_observation) # Call the new method
        self.last_observation = current_observation 
        info = self._get_info() 
        info["action_status"] = action_status
        info.update(action_specific_reward_info) # Add info from action handling

        # --- Calculate Reward ---
        reward = self._calculate_reward(base_action_cost, action_specific_reward_info, 
                                        self.last_observation, current_observation, 
                                        action_status, action)
        
        # --- Update State ---
        # self.last_observation is already updated above
        # self.player_is_in_combat_animation is already updated above

        terminated = False # Placeholder for death condition
        if current_observation["player_stats"][0] <= 0: # current_health
             terminated = True
             print("Player died. Episode terminated.")
        
        truncated = False # Placeholder for time limits, etc.
        
        return current_observation, reward, terminated, truncated, info

    # In class CustomGameEnv (ensure these are methods of the class):
    def _handle_attack_npc(self, last_observation):
        if not last_observation:
            print("Attack: No last_observation available.")
            return None, {}, {"attack_attempted": False, "error": "Missing last_observation"}

        player_loc_data = last_observation.get("player_location")
        # Check if player_loc_data is None or any of its crucial elements are None (assuming x,y,plane are at 0,1,2)
        if player_loc_data is None or \
           player_loc_data[0] is None or player_loc_data[1] is None or player_loc_data[2] is None or \
           player_loc_data[0] == 0.0 and player_loc_data[1] == 0.0: # Default/uninitialized check
             print("Attack: Player location not available or uninitialized in last_observation.")
             return None, {}, {"attack_attempted": False, "error": "Player location missing or uninitialized"}


        nearby_npcs = last_observation.get("nearby_npcs_info")
        if nearby_npcs is None:
            print("Attack: No NPC info in last_observation.")
            return None, {}, {"attack_attempted": False, "error": "NPC info missing"}

        # --- Player Animation for combat state ---
        # self.player_is_in_combat_animation should be updated in step() method after new obs.
        # For now, we'll simplify and not use it directly to gate re-attacking.

        best_target_goblin_id = None
        min_dist_sq = float('inf') # Use squared distance to avoid sqrt
        
        player_x, player_y, player_plane = player_loc_data[0], player_loc_data[1], player_loc_data[2]

        for i in range(MAX_NEARBY_NPCS):
            npc_id = nearby_npcs[i, 0]
            npc_x = nearby_npcs[i, 1]
            npc_y = nearby_npcs[i, 2]
            # npc_anim = nearby_npcs[i, 3] # NPC animation (could be used to check if already dead/fighting)

            if npc_id == GOBLIN_NPC_ID:
                # Basic check: is NPC data valid (not -1 padding)?
                if npc_x != -1 and npc_y != -1: # Assuming NPCs are on the same plane as player
                    dist_sq = (player_x - npc_x)**2 + (player_y - npc_y)**2
                    if dist_sq < min_dist_sq:
                        min_dist_sq = dist_sq
                        best_target_goblin_id = int(npc_id)
        
        if best_target_goblin_id is not None:
            # Simple logic: always try to attack if a goblin is found.
            # More complex: check if self.current_target_npc_id == best_target_goblin_id and self.player_is_in_combat_animation
            # For now, if we found a goblin, we set it as current target and attempt attack.
            self.current_target_npc_id = best_target_goblin_id 
            print(f"Attack: Found Goblin (ID: {best_target_goblin_id}). Min distance: {min_dist_sq**0.5:.2f}")
            return "attack_npc", {"npc_id": best_target_goblin_id}, {"attack_attempted": True, "target_id": best_target_goblin_id}
        else:
            print("Attack: No suitable Goblin found nearby.")
            self.current_target_npc_id = None
        return None, {}, {"attack_attempted": False, "error": "No suitable goblin found"}

    def _handle_eat_food(self, last_observation):
        if not last_observation:
            print("Eat Food: No last_observation available.")
            return None, {}, {"eat_attempted": False, "error": "Missing last_observation"}

        player_stats = last_observation.get("player_stats")
        if player_stats is None or len(player_stats) < 2: # Need at least current and max health
            print("Eat Food: Player stats not available or incomplete in last_observation.")
            return None, {}, {"eat_attempted": False, "error": "Player stats missing or incomplete"}

        current_health = player_stats[0]
        max_health = player_stats[1]

        if max_health <= 0: # Avoid division by zero if max_health isn't loaded correctly
            print("Eat Food: Max health is zero or invalid.")
            return None, {}, {"eat_attempted": False, "error": "Invalid max_health"}
            
        should_eat = (current_health / max_health) <= EAT_HEALTH_THRESHOLD_PERCENTAGE
        
        if not should_eat:
            # print(f"Eat Food: Health {current_health}/{max_health} is above threshold {EAT_HEALTH_THRESHOLD_PERCENTAGE*100}%. No need to eat.")
            return None, {}, {"eat_attempted": False, "status": "Health sufficient"}

        inventory_item_ids = last_observation.get("inventory_item_ids")
        if inventory_item_ids is None:
            print("Eat Food: Inventory info not available in last_observation.")
            return None, {}, {"eat_attempted": False, "error": "Inventory info missing"}

        found_food_id = None
        for i in range(MAX_INVENTORY_ITEMS):
            item_id = inventory_item_ids[i]
            if item_id != -1 and int(item_id) in FOOD_ITEM_IDS: # Ensure item_id is not padding and is in our list
                found_food_id = int(item_id)
                break 
        
        if found_food_id is not None:
            print(f"Eat Food: Health {current_health}/{max_health} is low. Found food (ID: {found_food_id}). Attempting to eat.")
            # Action string "Eat" is common. Some items might use "Consume".
            # The Java plugin's interactWithInventoryItem needs to handle this.
            return "interact_inventory", {"item_id": found_food_id, "action": "Eat"}, {"eat_attempted": True, "food_id": found_food_id}
        else:
            print(f"Eat Food: Health {current_health}/{max_health} is low, but no suitable food found in inventory.")
            return None, {}, {"eat_attempted": False, "error": "No food found"}

    def _calculate_reward(self, base_action_cost, action_specific_reward_info, 
                          prev_obs, current_obs, action_status, action_taken):
        reward = base_action_cost

        # --- Penalties for Action Failures/Context Errors ---
        if action_status.get("status") == "error": # Error from Java plugin or ZMQ
            reward -= 0.5
            print(f"Reward: Penalized for action error: {action_status.get('message')}")
        elif action_status.get("status") == "no_action_taken" and action_taken != 3: # Action was chosen but handler decided not to act (and not NOOP)
            # Check specific errors from handlers if available in action_specific_reward_info
            if action_specific_reward_info.get("error") == "No suitable goblin found" and action_taken == 0:
                reward -= 0.5 # Tried to attack when no goblin was found by handler
                print("Reward: Penalized for trying to attack with no suitable goblin.")
            elif action_specific_reward_info.get("error") == "No food found" and action_taken == 1:
                reward -= 0.3 # Tried to eat but no food
                print("Reward: Penalized for trying to eat with no food.")
            elif action_specific_reward_info.get("status") == "Health sufficient" and action_taken == 1:
                reward -= 0.3 # Tried to eat when health was high
                print("Reward: Penalized for trying to eat with sufficient health.")
            # Add more specific penalties based on action_specific_reward_info if needed

        # --- Rewards/Penalties based on Action Type and Outcome ---
        if action_status.get("status") == "submitted":
            reward += 0.1 # Small base reward for any successfully submitted action

            if action_taken == 0: # ATTACK_NPC
                if action_specific_reward_info.get("attack_attempted"):
                    reward += 0.5  # Successfully submitted an attack command
                    print("Reward: Bonus for submitting attack.")
                    # TODO (Advanced): Check if target NPC health decreased in current_obs vs prev_obs
                    # This would require adding NPC health to observation or having a way to query it.
                    # For now, this simple reward for submission is a starting point.

            elif action_taken == 1: # EAT_FOOD
                if action_specific_reward_info.get("eat_attempted"):
                    # Check if health actually increased (requires prev_obs to be valid)
                    if prev_obs and prev_obs.get("player_stats") is not None and \
                       current_obs.get("player_stats") is not None and \
                       len(prev_obs["player_stats"]) > 0 and len(current_obs["player_stats"]) > 0 and \
                       current_obs["player_stats"][0] > prev_obs["player_stats"][0]:
                        health_increase = current_obs["player_stats"][0] - prev_obs["player_stats"][0]
                        reward += health_increase * 0.5 # Reward proportional to healing, e.g., 5.0 for 10 hp
                        print(f"Reward: Bonus for eating and increasing health by {health_increase}.")
                    else:
                        # Submitted eat command, but health didn't increase (e.g., already full, non-food, or lag)
                        reward -= 0.1 # Small penalty or just remove the submission bonus
                        print("Reward: Eat submitted, but no health increase observed.")
            
            elif action_taken == 2: # MOVE_TO_GOBLIN_AREA
                reward += 0.05 # Small bonus for moving, already got 0.1 for submission
                print("Reward: Bonus for moving to waypoint.")

        # --- NOOP Action (action_taken == 3) ---
        if action_taken == 3: # NOOP
            # If base_action_cost is -0.1, this effectively makes NOOP cost 0 if we add 0.1
            # Or, set reward directly:
            reward = 0.0 # NOOPs are neutral or very slightly negative if preferred
            print("Reward: NOOP action, neutral reward.")


        # --- Major Penalty for Death ---
        if current_obs.get("player_stats") is not None and len(current_obs["player_stats"]) > 0 and \
           current_obs["player_stats"][0] <= 0: # Current health is 0 or less
            reward = -100.0 # Large penalty for dying
            print("Reward: Large penalty for player death.")
            
        print(f"Final Reward for step: {reward}")
        return reward

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
    for i in range(4): # Test all 4 new actions
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
