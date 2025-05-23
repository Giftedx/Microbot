"""
Integration tests for AIBridge Python-Java communication.
Tests the full communication pipeline and environment functionality.
"""

import pytest
import time
import json
import zmq
import threading
from unittest.mock import Mock, patch
from custom_env import CustomGameEnv
from zmq_client import ZMQClient


class MockZMQServer:
    """Mock ZMQ server to simulate the Java AIBridge plugin for testing."""
    
    def __init__(self, port=5556):  # Use different port to avoid conflicts
        self.port = port
        self.context = None
        self.socket = None
        self.running = False
        self.thread = None
        self.responses = {}
        self.received_messages = []
        
    def setup_default_responses(self):
        """Set up default mock responses for testing."""
        self.responses["command:get_observation"] = {
            "player_current_health": 75,
            "player_max_health": 99,
            "player_current_prayer": 50,
            "player_max_prayer": 70,
            "player_run_energy_percentage": 80.5,
            "player_animation": 808,
            "player_location": {"x": 3200, "y": 3200, "plane": 0},
            "nearby_npcs": [
                {
                    "name": "Goblin",
                    "id": 125,
                    "animation": 422,
                    "location": {"x": 3201, "y": 3201, "plane": 0}
                }
            ],
            "inventory": [
                {"id": 315, "name": "Shrimp", "quantity": 10},
                {"id": 526, "name": "Bones", "quantity": 5}
            ],
            "nearby_ground_items": [
                {
                    "id": 526,
                    "name": "Bones",
                    "quantity": 1,
                    "location": {"x": 3199, "y": 3199, "plane": 0}
                }
            ]
        }
        
        self.responses["command:execute_action:*"] = {
            "status": "submitted",
            "action_type": "test_action"
        }
    
    def start(self):
        """Start the mock server in a separate thread."""
        self.setup_default_responses()
        self.running = True
        self.thread = threading.Thread(target=self._server_loop)
        self.thread.start()
        time.sleep(0.1)  # Give server time to start
        
    def stop(self):
        """Stop the mock server."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        if self.socket:
            self.socket.close()
        if self.context:
            self.context.term()
            
    def _server_loop(self):
        """Main server loop handling ZMQ messages."""
        try:
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.REP)
            self.socket.bind(f"tcp://*:{self.port}")
            self.socket.setsockopt(zmq.RCVTIMEO, 1000)  # 1 second timeout
            
            while self.running:
                try:
                    message = self.socket.recv_string()
                    self.received_messages.append(message)
                    
                    # Find matching response
                    response = None
                    if message in self.responses:
                        response = self.responses[message]
                    elif message.startswith("command:execute_action:"):
                        response = self.responses.get("command:execute_action:*")
                    else:
                        response = {"status": "error", "message": f"Unknown command: {message}"}
                    
                    self.socket.send_string(json.dumps(response))
                    
                except zmq.Again:
                    continue  # Timeout, check if still running
                    
        except Exception as e:
            print(f"Mock server error: {e}")


class TestZMQClient:
    """Test ZMQClient functionality."""
    
    @pytest.fixture
    def mock_server(self):
        """Fixture providing a mock ZMQ server."""
        server = MockZMQServer()
        server.start()
        yield server
        server.stop()
    
    @pytest.fixture
    def zmq_client(self, mock_server):
        """Fixture providing a ZMQClient connected to mock server."""
        client = ZMQClient(port=mock_server.port)
        yield client
        client.close()
    
    def test_get_observation(self, zmq_client, mock_server):
        """Test getting observation from server."""
        obs = zmq_client.get_observation()
        
        assert obs is not None
        assert obs["player_current_health"] == 75
        assert obs["player_max_health"] == 99
        assert obs["player_location"]["x"] == 3200
        assert len(obs["nearby_npcs"]) == 1
        assert obs["nearby_npcs"][0]["name"] == "Goblin"
        
        # Verify server received correct message
        assert "command:get_observation" in mock_server.received_messages
    
    def test_execute_action(self, zmq_client, mock_server):
        """Test executing action via server."""
        result = zmq_client.execute_action("walk_to", {"x": 3100, "y": 3100})
        
        assert result is not None
        assert result["status"] == "submitted"
        
        # Verify server received correct message
        action_messages = [msg for msg in mock_server.received_messages 
                          if msg.startswith("command:execute_action:")]
        assert len(action_messages) == 1
        
        # Parse the action payload
        payload = action_messages[0].split("command:execute_action:", 1)[1]
        action_data = json.loads(payload)
        assert action_data["action_type"] == "walk_to"
        assert action_data["parameters"]["x"] == 3100
    
    def test_connection_timeout(self):
        """Test client behavior on connection timeout."""
        # Try to connect to non-existent server
        client = ZMQClient(port=9999)
        
        obs = client.get_observation()
        assert obs["status"] == "error"
        assert "timeout" in obs["message"].lower()
        
        client.close()
    
    def test_invalid_json_response(self, mock_server):
        """Test handling of invalid JSON response."""
        # Set up server to return invalid JSON
        mock_server.responses["command:get_observation"] = "invalid json"
        
        client = ZMQClient(port=mock_server.port)
        obs = client.get_observation()
        
        assert obs["status"] == "error"
        assert "Failed to decode JSON" in obs["message"]
        
        client.close()


class TestCustomGameEnv:
    """Test CustomGameEnv functionality."""
    
    @pytest.fixture
    def mock_server(self):
        """Fixture providing a mock ZMQ server."""
        server = MockZMQServer()
        server.start()
        yield server
        server.stop()
    
    @pytest.fixture
    def game_env(self, mock_server):
        """Fixture providing a CustomGameEnv with mocked communication."""
        with patch('custom_env.ZMQClient') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            
            # Set up mock client responses
            mock_client.get_observation.return_value = mock_server.responses["command:get_observation"]
            mock_client.execute_action.return_value = {"status": "submitted", "action_type": "test"}
            
            env = CustomGameEnv()
            yield env, mock_client
    
    def test_observation_space(self, game_env):
        """Test that observation space is properly defined."""
        env, _ = game_env
        
        obs_space = env.observation_space
        assert "player_stats" in obs_space.spaces
        assert "player_location" in obs_space.spaces
        assert "nearby_npcs_info" in obs_space.spaces
        assert "inventory_item_ids" in obs_space.spaces
        assert "nearby_ground_items_info" in obs_space.spaces
        assert "player_animation" in obs_space.spaces
    
    def test_action_space(self, game_env):
        """Test that action space is properly defined."""
        env, _ = game_env
        
        assert env.action_space.n == 4  # ATTACK_NPC, EAT_FOOD, MOVE_TO_GOBLIN_AREA, NOOP
    
    def test_reset(self, game_env):
        """Test environment reset functionality."""
        env, mock_client = game_env
        
        obs, info = env.reset()
        
        # Verify observation structure
        assert "player_stats" in obs
        assert "player_location" in obs
        assert "nearby_npcs_info" in obs
        assert "inventory_item_ids" in obs
        assert "nearby_ground_items_info" in obs
        assert "player_animation" in obs
        
        # Verify info structure
        assert "raw_observation" in info
        assert "npc_names" in info
        assert "inventory_item_names" in info
        assert "ground_item_names" in info
        
        # Verify client was called
        mock_client.get_observation.assert_called()
    
    def test_step_attack_npc(self, game_env):
        """Test ATTACK_NPC action."""
        env, mock_client = game_env
        
        # Reset environment first
        env.reset()
        
        # Execute ATTACK_NPC action
        obs, reward, terminated, truncated, info = env.step(0)  # Action 0 = ATTACK_NPC
        
        # Verify action was executed
        mock_client.execute_action.assert_called()
        call_args = mock_client.execute_action.call_args
        assert call_args[0][0] == "attack_npc"  # action_type
        assert "npc_id" in call_args[0][1]  # parameters
        
        # Verify observation is returned
        assert obs is not None
        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
    
    def test_step_eat_food(self, game_env):
        """Test EAT_FOOD action."""
        env, mock_client = game_env
        
        env.reset()
        obs, reward, terminated, truncated, info = env.step(1)  # Action 1 = EAT_FOOD
        
        # Verify action was attempted (might not execute if no food)
        mock_client.get_observation.assert_called()
    
    def test_step_move_to_goblin_area(self, game_env):
        """Test MOVE_TO_GOBLIN_AREA action."""
        env, mock_client = game_env
        
        env.reset()
        obs, reward, terminated, truncated, info = env.step(2)  # Action 2 = MOVE_TO_GOBLIN_AREA
        
        # Verify walk_to action was executed
        mock_client.execute_action.assert_called()
        call_args = mock_client.execute_action.call_args
        assert call_args[0][0] == "walk_to"  # action_type
        assert "x" in call_args[0][1]  # parameters
        assert "y" in call_args[0][1]  # parameters
    
    def test_step_noop(self, game_env):
        """Test NOOP action."""
        env, mock_client = game_env
        
        env.reset()
        obs, reward, terminated, truncated, info = env.step(3)  # Action 3 = NOOP
        
        # NOOP should not execute any game action
        # Only get_observation should be called for getting new state
        mock_client.get_observation.assert_called()
    
    def test_error_handling_invalid_observation(self, game_env):
        """Test handling of invalid observation data."""
        env, mock_client = game_env
        
        # Set up client to return error
        mock_client.get_observation.return_value = {
            "status": "error", 
            "message": "Test error"
        }
        
        obs, info = env.reset()
        
        # Environment should handle error gracefully with default observation
        assert obs is not None
        assert all(key in obs for key in env.observation_space.spaces.keys())
    
    def test_reward_calculation(self, game_env):
        """Test reward calculation logic."""
        env, mock_client = game_env
        
        # Set up specific observation for reward testing
        mock_obs = {
            "player_current_health": 50,  # Lower health
            "player_max_health": 99,
            "player_current_prayer": 70,
            "player_max_prayer": 70,
            "player_run_energy_percentage": 80.0,
            "player_animation": 422,  # Combat animation
            "player_location": {"x": 3200, "y": 3200, "plane": 0},
            "nearby_npcs": [{"name": "Goblin", "id": 125, "animation": -1, 
                           "location": {"x": 3201, "y": 3201, "plane": 0}}],
            "inventory": [{"id": 315, "name": "Shrimp", "quantity": 5}],
            "nearby_ground_items": [{"id": 526, "name": "Bones", "quantity": 1,
                                   "location": {"x": 3199, "y": 3199, "plane": 0}}]
        }
        
        mock_client.get_observation.return_value = mock_obs
        
        env.reset()
        obs, reward, terminated, truncated, info = env.step(0)  # Attack action
        
        # Reward should be calculated based on health, combat, etc.
        assert isinstance(reward, (int, float))


class TestIntegrationWorkflow:
    """Test complete integration workflows."""
    
    @pytest.fixture
    def mock_server(self):
        """Fixture providing a mock ZMQ server."""
        server = MockZMQServer()
        server.start()
        yield server
        server.stop()
    
    def test_complete_training_episode(self, mock_server):
        """Test a complete training episode from start to finish."""
        with patch('custom_env.ZMQClient') as mock_client_class:
            mock_client = Mock()
            mock_client_class.return_value = mock_client
            
            # Set up dynamic responses to simulate game state changes
            observations = [
                mock_server.responses["command:get_observation"],
                {**mock_server.responses["command:get_observation"], 
                 "player_current_health": 60},  # Health decreased
                {**mock_server.responses["command:get_observation"], 
                 "player_current_health": 80},  # Health restored after eating
            ]
            
            mock_client.get_observation.side_effect = observations
            mock_client.execute_action.return_value = {"status": "submitted"}
            
            env = CustomGameEnv()
            
            # Run a short episode
            obs, info = env.reset()
            total_reward = 0
            
            for step in range(3):
                action = step % 4  # Cycle through all actions
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                
                if terminated or truncated:
                    break
            
            # Verify episode completed successfully
            assert isinstance(total_reward, (int, float))
            assert mock_client.get_observation.call_count >= 3
    
    def test_connection_recovery(self, mock_server):
        """Test system behavior during connection issues."""
        # This would test reconnection logic if implemented
        pass


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"]) 