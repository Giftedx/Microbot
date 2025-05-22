import zmq
import json
import time

class ZMQClient:
    def __init__(self, host="localhost", port=5555):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect(f"tcp://{host}:{port}")
        # Set a timeout for receive operations (e.g., 5 seconds)
        self.socket.setsockopt(zmq.RCVTIMEO, 5000)
        self.socket.setsockopt(zmq.LINGER, 0) # Don't wait for unsent messages on close


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

        try:
            # print(f"Sending: {raw_message}") # For debugging
            self.socket.send_string(raw_message)
            response_bytes = self.socket.recv()
            response_str = response_bytes.decode('utf-8')
            # print(f"Received: {response_str}") # For debugging
            try:
                return json.loads(response_str)
            except json.JSONDecodeError as e:
                error_msg = f"Failed to decode JSON response: {response_str}. Error: {e}"
                print(error_msg)
                return {"status": "error", "message": error_msg, "raw_response": response_str}
        except zmq.error.Again: # Timeout
            error_msg = f"Timeout waiting for ZMQ response to command: {raw_message}"
            print(error_msg)
            # Consider logging this to a file as well if it becomes frequent
            return {"status": "error", "message": "ZMQ timeout"}
        except zmq.error.ZMQError as e: # Other ZMQ errors
            error_msg = f"ZMQError during communication for command {raw_message}: {e}"
            print(error_msg)
            return {"status": "error", "message": error_msg}
        except Exception as e: # Other unexpected errors
            error_msg = f"Unexpected error during ZMQ communication for command {raw_message}: {e}"
            print(error_msg)
            return {"status": "error", "message": error_msg}

    def get_observation(self):
        return self.send_command("get_observation")

    def execute_action(self, action_type, parameters):
        # The 'params' for send_command in this case is the dict containing action_type and its own parameters
        action_payload = {"action_type": action_type, "parameters": parameters}
        return self.send_command("execute_action", params=action_payload)

    def close(self):
        self.socket.close()
        self.context.term()

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


    finally:
        client.close()
        print("Client closed.")
