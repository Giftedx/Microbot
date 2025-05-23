import zmq
import json
import time
from monitoring import record_error, get_metrics_collector

class ZMQClient:
    def __init__(self, host="localhost", port=5555):
        self.host = host
        self.port = port
        self.context = None
        self.socket = None
        self.connected = False
        self.connection_attempts = 0
        self.last_successful_communication = 0
        self.metrics = get_metrics_collector()
        
        self._initialize_connection()

    def _initialize_connection(self):
        """Initialize ZMQ connection with error handling."""
        try:
            self.context = zmq.Context()
            self.socket = self.context.socket(zmq.REQ)
            self.socket.connect(f"tcp://{self.host}:{self.port}")
            # Set a timeout for receive operations (e.g., 5 seconds)
            self.socket.setsockopt(zmq.RCVTIMEO, 5000)
            self.socket.setsockopt(zmq.LINGER, 0) # Don't wait for unsent messages on close
            self.connected = True
            self.connection_attempts += 1
            print(f"ZMQ Client connected to tcp://{self.host}:{self.port}")
        except Exception as e:
            self.connected = False
            record_error("ZMQ_INIT_ERROR", f"Failed to initialize ZMQ connection: {str(e)}")
            raise

    def _reconnect(self):
        """Attempt to reconnect if connection is lost."""
        if self.connected:
            return True
            
        try:
            if self.socket:
                self.socket.close()
            if self.context:
                self.context.term()
            
            time.sleep(1)  # Brief delay before reconnect
            self._initialize_connection()
            return True
        except Exception as e:
            record_error("ZMQ_RECONNECT_ERROR", f"Failed to reconnect: {str(e)}")
            self.metrics.record_connection_failure()
            return False

    def send_command(self, command_type, params=None):
        message = {"command_type": command_type}
        if params:
            message["params"] = params
        
        # For AI Bridge, commands are prefixed
        if command_type == "get_observation":
            raw_message = "command:get_observation"
        elif command_type == "execute_action":
            # The action_type and parameters for execute_action are wrapped in the 'params' dict
            # which then becomes the JSON payload for "command:execute_action:"
            if not params or "action_type" not in params:
                raise ValueError("Missing 'action_type' in params for execute_action")
            raw_message = f"command:execute_action:{json.dumps(params)}"
        else:
            raise ValueError(f"Unknown command_type for ZMQClient: {command_type}")

        # Track communication timing
        start_time = time.time()
        
        try:
            # Ensure we're connected
            if not self.connected:
                if not self._reconnect():
                    return {"status": "error", "message": "Connection failed"}
            
            # print(f"Sending: {raw_message}") # For debugging
            self.socket.send_string(raw_message)
            response_bytes = self.socket.recv()
            response_str = response_bytes.decode('utf-8')
            
            # Record successful communication
            self.last_successful_communication = time.time()
            communication_time_ms = (self.last_successful_communication - start_time) * 1000
            
            # print(f"Received: {response_str}") # For debugging
            try:
                response = json.loads(response_str)
                
                # Log performance for observations
                if command_type == "get_observation":
                    self.metrics.record_observation_time(communication_time_ms)
                elif command_type == "execute_action":
                    self.metrics.record_action_time(communication_time_ms)
                
                return response
            except json.JSONDecodeError as e:
                error_msg = f"Failed to decode JSON response: {response_str}. Error: {e}"
                print(error_msg)
                record_error("ZMQ_JSON_DECODE_ERROR", error_msg, {"raw_response": response_str})
                return {"status": "error", "message": error_msg, "raw_response": response_str}
                
        except zmq.error.Again: # Timeout
            error_msg = f"Timeout waiting for ZMQ response to command: {raw_message}"
            print(error_msg)
            record_error("ZMQ_TIMEOUT", error_msg, {"command": raw_message})
            self.connected = False  # Mark as disconnected on timeout
            # Consider logging this to a file as well if it becomes frequent
            return {"status": "error", "message": "ZMQ timeout"}
        except zmq.error.ZMQError as e: # Other ZMQ errors
            error_msg = f"ZMQError during communication for command {raw_message}: {e}"
            print(error_msg)
            record_error("ZMQ_ERROR", error_msg, {"command": raw_message})
            self.connected = False  # Mark as disconnected on ZMQ error
            return {"status": "error", "message": error_msg}
        except Exception as e: # Other unexpected errors
            error_msg = f"Unexpected error during ZMQ communication for command {raw_message}: {e}"
            print(error_msg)
            record_error("ZMQ_UNEXPECTED_ERROR", error_msg, {"command": raw_message})
            self.connected = False  # Mark as disconnected on unexpected error
            return {"status": "error", "message": error_msg}

    def get_observation(self):
        return self.send_command("get_observation")

    def execute_action(self, action_type, parameters):
        # The 'params' for send_command in this case is the dict containing action_type and its own parameters
        action_payload = {"action_type": action_type, "parameters": parameters}
        return self.send_command("execute_action", params=action_payload)

    def is_connected(self):
        """Check if the client is currently connected."""
        if not self.connected:
            return False
        
        # Check if communication is recent (within last 30 seconds)
        current_time = time.time()
        if current_time - self.last_successful_communication > 30:
            return False
        
        return True

    def get_connection_stats(self):
        """Get connection statistics for monitoring."""
        return {
            "connected": self.connected,
            "connection_attempts": self.connection_attempts,
            "last_successful_communication": self.last_successful_communication,
            "host": self.host,
            "port": self.port
        }

    def close(self):
        try:
            if self.socket:
                self.socket.close()
            if self.context:
                self.context.term()
            self.connected = False
            print("ZMQ Client connection closed")
        except Exception as e:
            record_error("ZMQ_CLOSE_ERROR", f"Error closing ZMQ connection: {str(e)}")

if __name__ == '__main__':
    client = ZMQClient()
    try:
        # Test observation
        print("Requesting observation...")
        obs = client.get_observation()
        print(f"Observation: {obs}")
        time.sleep(1)

        # Test an action (example: walk_to)
        print("Executing walk_to action...")
        action_result = client.execute_action("walk_to", {"x": 3200, "y": 3200, "plane": 0})
        print(f"Action Result: {action_result}")
        time.sleep(1)
        
        # Test another action (example: type_string)
        print("Executing type_string action...")
        action_result_type = client.execute_action("type_string", {"text": "Hello from Python AI!"})
        print(f"Action Result: {action_result_type}")

        # Print connection stats
        print("Connection Stats:", client.get_connection_stats())

    finally:
        client.close()
        print("Client closed.")
