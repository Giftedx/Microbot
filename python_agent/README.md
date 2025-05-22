# AI Agent Integration via AIBridgePlugin

This directory contains the Python components for creating an AI agent that interacts with the RuneLite client via the `AIBridgePlugin`.

## Overview

The system uses a ZeroMQ (ZMQ) message queue for communication between a Java-based RuneLite plugin (`AIBridgePlugin`) and a Python-based AI agent.

- **Java Plugin (`AIBridgePlugin`)**: Runs within RuneLite, provides game state observations, and executes actions in the game.
- **Python Agent (`custom_env.py`, `train_agent.py`)**: Runs externally, makes decisions, and learns using libraries like Gymnasium and Stable Baselines3.

## Communication Protocol

- **Transport**: ZeroMQ (REQ-REP pattern)
- **Address**: `tcp://localhost:5555` (Python client connects to this, Java plugin binds to `tcp://*:5555`)

### Messages from Python to Java

1.  **Request Observation:**
    -   Plain string: `command:get_observation`

2.  **Execute Action:**
    -   Plain string starting with `command:execute_action:` followed by a JSON payload.
    -   Example: `command:execute_action:{"action_type": "walk_to", "parameters": {"x": 3200, "y": 3200, "plane": 0}}`

    **Supported `action_type` values and their `parameters`:**
    *   `type_string`:
        *   `parameters`: `{"text": "string_to_type"}`
    *   `attack_npc`:
        *   `parameters`: `{"npc_id": npc_id_integer}`
    *   `interact_object`:
        *   `parameters`: `{"object_id": object_id_integer, "action": "action_string (e.g., Open, Close)"}` (action is optional, defaults if not provided based on Java logic)
    *   `interact_inventory`:
        *   `parameters`: `{"item_id": item_id_integer, "action": "action_string (e.g., Use, Drop)"}` (action is optional)
    *   `interact_ground_item`:
        *   `parameters`: `{"item_id": item_id_integer, "x": optional_world_x, "y": optional_world_y, "plane": optional_plane}`
        *   (Note: If x,y,plane are provided, it targets that specific stack, otherwise the closest stack of that item ID.)
    *   `click_widget`:
        *   `parameters`: `{"widget_id": integer_group_id, "child_id": integer_child_id}` (child_id is optional, -1 if none)
    *   `walk_to`:
        *   `parameters`: `{"x": world_x_coord, "y": world_y_coord, "plane": integer_plane (optional, defaults to current plane)}`
    *   `invoke_menu_action_detailed`:
        *   `parameters`: `{"option": "string", "target": "string", "id": int, "opcode": int, "param0": int, "param1": int, "force_left_click": boolean (optional)}`
        *   (Allows precise, low-level control over menu interactions.)

### Messages from Java to Python (Responses)

All responses from the Java plugin are JSON strings.

1.  **Observation Response (for `command:get_observation`):**
    ```json
    {
      "player_current_health": int,
      "player_max_health": int,
      "player_current_prayer": int,
      "player_max_prayer": int,
      "player_run_energy_percentage": float, // 0.0 to 1.0
      "player_location": {"x": int, "y": int, "plane": int} or null,
      "nearby_npcs": [ // List, up to MAX_NEARBY_NPCS (e.g., 3)
        {"id": int, "name": "string", "animation": int, "location": {"x": int, "y": int, "plane": int}}, 
        // ...
      ],
      "inventory": [ // List, up to MAX_INVENTORY_ITEMS (e.g., 5)
        {"id": int, "quantity": int, "name": "string"},
        // ...
      ],
      "nearby_ground_items": [ // List, up to MAX_GROUND_ITEMS (e.g., 5)
        {"id": int, "quantity": int, "name": "string", "location": {"x": int, "y": int, "plane": int}},
        // ...
      ]
    }
    ```
    If not logged in or error, may be: `{"status": "error", "message": "Not logged in or client not available"}`

2.  **Action Response (for `command:execute_action`):**
    ```json
    {
      "status": "submitted" or "error" or "no_action_taken",
      "action_type": "original_action_type",
      "message": "optional_error_message_if_status_is_error"
    }
    ```

## Python Agent Setup

1.  **Create a virtual environment (recommended):**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate
    ```
2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    The `requirements.txt` includes:
    - `pyzmq`
    - `gymnasium`
    - `numpy`
    - `stable-baselines3[extra]` (for PPO agent and common dependencies like PyTorch)

## Running the System

1.  **Start RuneLite:** Launch RuneLite and ensure the `AIBridgePlugin` is enabled in the plugin settings. The ZMQ server in the plugin will start automatically.
2.  **Run the Python training script:**
    ```bash
    python train_agent.py
    ```
    This will initialize the `CustomGameEnv`, which connects to the Java plugin, and start training the PPO agent. Logs and trained models will be saved to `sb3_logs/` and `sb3_models/` respectively.

## Customizing for New Tasks

1.  **Java Plugin (`AIBridgePlugin.java`):**
    *   If new observations are needed, update `getGameObservationJson()`.
    *   If new actions are needed, add them to `handleAction()` and create corresponding helper methods for game interaction.
2.  **Python Environment (`custom_env.py`):**
    *   **Observation Space:** Modify `self.observation_space` in `__init__` to match any new data from Java. Update `_get_obs()` to parse this new data correctly.
    *   **Action Space:** Add new actions to `self.action_space` in `__init__`. Update `step()` to map these new discrete actions to the appropriate `action_type` and `parameters` for `self.client.execute_action()`.
    *   **Reward Function:** The core of task-specific AI. Modify the reward calculation in the `step()` method to incentivize the desired behavior for your new task.
    *   **Constants:** Update constants like `MAX_NEARBY_NPCS`, `BONE_ITEM_ID`, etc., as needed.

## Included Python Files

-   `zmq_client.py`: Handles ZMQ communication with the Java plugin.
-   `custom_env.py`: Defines the Gymnasium environment (`CustomGameEnv`) for interacting with the game.
-   `train_agent.py`: Example script to train a Stable Baselines3 PPO agent using `CustomGameEnv`.
-   `requirements.txt`: Python dependencies.

```
