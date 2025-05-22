import unittest
import numpy as np
from unittest.mock import MagicMock

# Important: Add python_agent to sys.path if tests are run from root or another directory
# For simplicity, assume tests might be run from within python_agent directory or PYTHONPATH is set.
# If running with `python -m unittest discover ./python_agent` from root, imports should work.
try:
    from custom_env import CustomGameEnv, MAX_NEARBY_NPCS, MAX_INVENTORY_ITEMS, MAX_GROUND_ITEMS, BONE_ITEM_ID
except ImportError:
    # Fallback for running directly from python_agent or if path issues occur
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from custom_env import CustomGameEnv, MAX_NEARBY_NPCS, MAX_INVENTORY_ITEMS, MAX_GROUND_ITEMS, BONE_ITEM_ID


class TestCustomGameEnv(unittest.TestCase):

    def setUp(self):
        # Mock the ZMQClient to avoid actual network calls
        self.mock_zmq_client = MagicMock()
        
        # Instantiate the environment, replacing its client with the mock
        self.env = CustomGameEnv()
        self.env.client = self.mock_zmq_client
        
        # Provide a default observation for reset to populate last_observation
        self.mock_zmq_client.get_observation.return_value = self._get_default_raw_obs()
        self.env.reset() # Initialize last_observation

    def _get_default_raw_obs(self):
        return {
            "status": "success",
            "player_current_health": 100, "player_max_health": 100,
            "player_current_prayer": 50, "player_max_prayer": 50,
            "player_run_energy_percentage": 0.8,
            "player_location": {"x": 3200, "y": 3200, "plane": 0},
            "nearby_npcs": [], "inventory": [], "nearby_ground_items": []
        }

    def test_get_obs_initialization_on_error(self):
        self.mock_zmq_client.get_observation.return_value = {"status": "error", "message": "Test error"}
        obs = self.env._get_obs()
        
        self.assertIsInstance(obs, dict)
        # Check if all parts of observation are default (zeros or -1s)
        self.assertTrue(np.all(obs["player_stats"] == np.zeros_like(obs["player_stats"])))
        self.assertTrue(np.all(obs["player_location"] == 0.0)) # Defaulted to 0,0,0
        self.assertTrue(np.all(obs["nearby_npcs_info"] == -1.0))
        self.assertTrue(np.all(obs["inventory_item_ids"] == -1.0))
        self.assertTrue(np.all(obs["nearby_ground_items_info"] == -1.0))

    def test_get_obs_parsing_correct_data(self):
        raw_obs = self._get_default_raw_obs()
        raw_obs["nearby_npcs"] = [{"id": 123, "name": "Goblin", "animation": 1, "location": {"x": 3201, "y": 3201, "plane": 0}}]
        raw_obs["inventory"] = [{"id": BONE_ITEM_ID, "name": "Bones", "quantity": 1}]
        raw_obs["nearby_ground_items"] = [{"id": BONE_ITEM_ID, "name": "Bones", "quantity": 1, "location": {"x": 3202, "y": 3202, "plane": 0}}]
        
        self.mock_zmq_client.get_observation.return_value = raw_obs
        obs = self.env._get_obs() # This call also populates self.env._current_game_info

        self.assertEqual(obs["player_stats"][0], 100)
        self.assertEqual(obs["player_location"][0], 3200)
        
        self.assertEqual(obs["nearby_npcs_info"][0, 0], 123) # ID
        self.assertEqual(obs["nearby_npcs_info"][0, 1], 3201) # X
        self.assertEqual(obs["nearby_npcs_info"][0, 3], 1)    # Animation

        self.assertEqual(obs["inventory_item_ids"][0], BONE_ITEM_ID)
        self.assertEqual(obs["nearby_ground_items_info"][0, 0], BONE_ITEM_ID) # ID
        self.assertEqual(obs["nearby_ground_items_info"][0, 1], 1)          # Quantity
        self.assertEqual(obs["nearby_ground_items_info"][0, 2], 3202)       # X

        # Check names in _current_game_info (which _get_info returns)
        info = self.env._get_info() # _get_info now returns self.env._current_game_info
        self.assertEqual(info["npc_names"][0], "Goblin")
        self.assertEqual(info["inventory_item_names"][0], "Bones")
        self.assertEqual(info["ground_item_names"][0], "Bones")


    def test_get_obs_missing_keys(self):
        raw_obs = {"status": "success", "player_current_health": 90} # Missing many keys
        self.mock_zmq_client.get_observation.return_value = raw_obs
        obs = self.env._get_obs()
        self.assertEqual(obs["player_stats"][0], 90)
        self.assertEqual(obs["player_stats"][1], 0) # Default for max_health
        self.assertTrue(np.all(obs["player_location"] == 0.0))


    def test_step_action_mapping_type_string(self):
        # self.env.last_observation is already populated by setUp's reset call
        self.mock_zmq_client.execute_action.return_value = {"status": "submitted"}
        # The _get_obs call during step will use the default mock return value
        self.mock_zmq_client.get_observation.return_value = self._get_default_raw_obs()
        _, _, _, _, info = self.env.step(0) # Action 0 = type_string
        
        self.mock_zmq_client.execute_action.assert_called_once_with(
            "type_string", {"text": "Hello AI from Gym Env"}
        )
        self.assertEqual(info["action_status"]["status"], "submitted")

    def test_step_pickup_bone_no_bones_visible(self):
        # Ensure last_observation is set and has no bones
        empty_obs_data = self._get_default_raw_obs()
        self.mock_zmq_client.get_observation.return_value = empty_obs_data # for _get_obs calls
        self.env.last_observation = self.env._get_obs() # Populate last_observation with no bones

        self.mock_zmq_client.execute_action.reset_mock() # Reset call count
        _, reward, _, _, _ = self.env.step(5) # Action 5 = pickup_bone
        
        self.mock_zmq_client.execute_action.assert_not_called()
        self.assertEqual(reward, -1.0) # Penalty for trying to pick up non-visible bones

    def test_step_pickup_bone_bones_visible(self):
        # Ensure last_observation is set and has bones
        obs_with_bones = self._get_default_raw_obs()
        obs_with_bones["nearby_ground_items"] = [
            {"id": BONE_ITEM_ID, "name": "Bones", "quantity": 1, "location": {"x": 3202, "y": 3202, "plane": 0}}
        ]
        # This will be returned for the _get_obs call that sets self.last_observation
        self.mock_zmq_client.get_observation.return_value = obs_with_bones 
        self.env.last_observation = self.env._get_obs()
        
        self.mock_zmq_client.execute_action.return_value = {"status": "submitted"}
        self.mock_zmq_client.execute_action.reset_mock()

        # Prime the next observation after action (bones gone)
        obs_after_pickup = self._get_default_raw_obs() 
        obs_after_pickup["nearby_ground_items"] = [] # Bones are gone
        # This will be returned for the _get_obs call at the end of the step method
        self.mock_zmq_client.get_observation.return_value = obs_after_pickup
        
        _, reward, _, _, info = self.env.step(5) # Action 5 = pickup_bone
        
        self.mock_zmq_client.execute_action.assert_called_once_with(
            "interact_ground_item", {"item_id": BONE_ITEM_ID}
        )
        self.assertEqual(info["action_status"]["status"], "submitted")
        # Reward: -0.1 (cost of action) + 10.0 (pickup bonus) = 9.9
        self.assertAlmostEqual(reward, 9.9)

    def test_step_unknown_action(self):
        # self.env.last_observation is populated by setUp
        self.mock_zmq_client.get_observation.return_value = self._get_default_raw_obs() # For _get_obs in step
        _, reward, _, _, _ = self.env.step(99) # Invalid action index
        self.assertEqual(reward, -1.0)


    def tearDown(self):
        self.env.close() # Ensure ZMQ client is closed

if __name__ == '__main__':
    unittest.main()
