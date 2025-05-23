package net.runelite.client.plugins.aibridge;

import javax.inject.Inject;
import net.runelite.client.plugins.Plugin;
import net.runelite.client.plugins.PluginDescriptor;
import lombok.extern.slf4j.Slf4j;
import org.zeromq.SocketType;
import org.zeromq.ZContext;
import org.zeromq.ZMQ;
import net.runelite.api.Client;
import net.runelite.api.Skill;
import net.runelite.api.Player;
import net.runelite.api.coords.WorldPoint;
import net.runelite.api.GameState;
import net.runelite.api.Item;
import net.runelite.api.ItemContainer;
import net.runelite.api.InventoryID;
import net.runelite.api.NPC;
import net.runelite.api.MenuAction;
import net.runelite.api.MenuEntry;
import net.runelite.api.Tile;
import net.runelite.api.TileObject;
import net.runelite.api.GameObject;
import net.runelite.api.WallObject;
import net.runelite.api.GroundObject;
import net.runelite.api.DecorativeObject;
import net.runelite.api.widgets.Widget;
import net.runelite.api.widgets.WidgetInfo;
import net.runelite.client.callback.ClientThread;
import net.runelite.api.TileItem; // For ground items
import net.runelite.api.Constants; // For SCENE_SIZE
import net.runelite.api.ItemComposition; // To get item names
import com.google.gson.Gson;
import com.google.gson.reflect.TypeToken;
import java.lang.reflect.Type;
import java.util.List;
import java.util.ArrayList;
import java.util.Map;
import java.util.HashMap;
import net.runelite.api.ObjectComposition;
import net.runelite.api.gameval.ComponentID;
import net.runelite.api.gameval.InventoryID;


@PluginDescriptor(
        name = "AI Bridge",
        description = "Provides a bridge for AI agents to interact with the game.",
        tags = {"ai", "automation", "bot"}
)
@Slf4j
public class AIBridgePlugin extends Plugin {
    @Inject
    private AIBridgeConfig config;

    @Inject
    private Client client;

    @Inject
    private Gson gson;

    @Inject
    private ClientThread clientThread;

    private ZContext context;
    private ZMQ.Socket socket;
    private Thread listenerThread;

    private String getGameObservationJson() {
        if (client == null) {
            return gson.toJson(Map.of("status", "error", "message", "Client is null."));
        }
        if (client.getGameState() != GameState.LOGGED_IN) {
            return gson.toJson(Map.of("status", "error", "message", "Not logged in. Current state: " + client.getGameState()));
        }

        Map<String, Object> observation = new HashMap<>();
        observation.put("player_current_health", client.getBoostedSkillLevel(Skill.HITPOINTS));
        observation.put("player_max_health", client.getRealSkillLevel(Skill.HITPOINTS));
        observation.put("player_current_prayer", client.getBoostedSkillLevel(Skill.PRAYER));
        observation.put("player_max_prayer", client.getRealSkillLevel(Skill.PRAYER));
        observation.put("player_run_energy_fraction", client.getEnergy() / 10000.0); // Normalize getEnergy() from 0-10000 to 0-1

        Player localPlayer = client.getLocalPlayer();
        if (localPlayer != null) {
            observation.put("player_animation", localPlayer.getAnimation());
            WorldPoint playerLocation = localPlayer.getWorldLocation();
            Map<String, Integer> locationMap = new HashMap<>();
            locationMap.put("x", playerLocation.getX());
            locationMap.put("y", playerLocation.getY());
            locationMap.put("plane", playerLocation.getPlane());
            observation.put("player_location", locationMap);
        } else {
            observation.put("player_animation", -1); // Default if no localPlayer
            observation.put("player_location", null);
            // If localPlayer is null, other player-dependent observations will be empty or default.
        }

        List<Map<String, Object>> npcList = new ArrayList<>();
        if (localPlayer != null) { // Check localPlayer before accessing it for NPCs
            for (NPC npc : client.getNpcs()) {
                if (npc != null && npc.getWorldLocation().distanceTo(localPlayer.getWorldLocation()) <= 10) {
                    Map<String, Object> npcData = new HashMap<>();
                    npcData.put("name", npc.getName()); 
                    npcData.put("animation", npc.getAnimation());
                    npcData.put("id", npc.getId());
                    Map<String, Integer> npcLocationMap = new HashMap<>();
                    npcLocationMap.put("x", npc.getWorldLocation().getX());
                    npcLocationMap.put("y", npc.getWorldLocation().getY());
                    npcLocationMap.put("plane", npc.getWorldLocation().getPlane());
                    npcData.put("location", npcLocationMap);
                    npcList.add(npcData);
                }
            }
        }
        observation.put("nearby_npcs", npcList);

        List<Map<String, Object>> inventoryItems = new ArrayList<>();
        ItemContainer inventory = client.getItemContainer(InventoryID.INVENTORY);
        if (inventory != null) {
            for (Item item : inventory.getItems()) {
                if (item != null && item.getId() != -1) {
                    Map<String, Object> itemData = new HashMap<>();
                    itemData.put("id", item.getId());
                    itemData.put("quantity", item.getQuantity());
                    ItemComposition itemDef = client.getItemDefinition(item.getId());
                    itemData.put("name", itemDef != null ? itemDef.getName() : "Unknown");
                    inventoryItems.add(itemData);
                }
            }
        }
        observation.put("inventory", inventoryItems);

        List<Map<String, Object>> groundItemsList = new ArrayList<>();
        if (localPlayer != null) {
            WorldPoint playerPos = localPlayer.getWorldLocation();
            int range = 10; // Range to search for ground items
            Tile[][][] sceneTiles = client.getScene().getTiles();
            int z = client.getPlane();
            if (sceneTiles != null && z >= 0 && z < sceneTiles.length && z < Constants.MAX_Z) { // Added MAX_Z check
                // Calculate player's scene coordinates
                int playerSceneX = playerPos.getX() - client.getBaseX();
                int playerSceneY = playerPos.getY() - client.getBaseY();
                
                // Calculate boundaries for the loop, ensuring they stay within valid scene bounds
                int minX = Math.max(0, playerSceneX - range);
                int maxX = Math.min(Constants.SCENE_SIZE - 1, playerSceneX + range);
                int minY = Math.max(0, playerSceneY - range);
                int maxY = Math.min(Constants.SCENE_SIZE - 1, playerSceneY + range);
                
                // Only loop over tiles within the player's range
                for (int x = minX; x <= maxX; ++x) {
                    for (int y = minY; y <= maxY; ++y) {
                        Tile tile = sceneTiles[z][x][y];
                        if (tile == null) continue;
                        List<TileItem> itemsOnTile = tile.getGroundItems();
                        if (itemsOnTile != null) {
                            for (TileItem item : itemsOnTile) {
                                if (item != null && tile.getWorldLocation().distanceTo(playerPos) <= range) {
                                    Map<String, Object> itemData = new HashMap<>();
                                    itemData.put("id", item.getId());
                                    itemData.put("quantity", item.getQuantity());
                                    WorldPoint itemWp = tile.getWorldLocation();
                                    Map<String, Integer> itemLocationMap = new HashMap<>();
                                    itemLocationMap.put("x", itemWp.getX());
                                    itemLocationMap.put("y", itemWp.getY());
                                    itemLocationMap.put("plane", itemWp.getPlane());
                                    itemData.put("location", itemLocationMap);
                                    ItemComposition groundItemDef = client.getItemDefinition(item.getId());
                                    itemData.put("name", groundItemDef != null ? groundItemDef.getName() : "Unknown");
                                    groundItemsList.add(itemData);
                                }
                            }
                        }
                    }
                }
            }
        }
        observation.put("nearby_ground_items", groundItemsList);

        return gson.toJson(observation);
    }

    @Override
    protected void startUp() throws Exception {
        log.info("AI Bridge starting up...");
        context = new ZContext();
        socket = context.createSocket(SocketType.REP);
        socket.bind("tcp://*:5555");

        listenerThread = new Thread(() -> {
            while (!Thread.currentThread().isInterrupted()) {
                try {
                    // Wait for next request from client
                    byte[] request = socket.recv(0);
                    String message = new String(request, ZMQ.CHARSET);
                    log.info("Received request: " + message);

                    // Process the request
                    String reply = "Error: Unknown command"; // Default reply for unknown commands
                    if ("hello".equalsIgnoreCase(message)) {
                        reply = "Received hello";
                    } else if ("command:get_observation".equalsIgnoreCase(message)) {
                        reply = getGameObservationJson();
                    } else if (message != null && message.startsWith("command:execute_action:")) {
                        String jsonPayload = message.substring("command:execute_action:".length());
                        try {
                            Type type = new TypeToken<Map<String, Object>>(){}.getType();
                            Map<String, Object> actionDetails = gson.fromJson(jsonPayload, type);
                            reply = handleAction(actionDetails);
                        } catch (Exception e) {
                            log.error("Failed to parse or handle action: " + jsonPayload, e);
                            reply = gson.toJson(Map.of("status", "error", "message", "Failed to handle action: " + e.getMessage()));
                        }
                    }

                    socket.send(reply.getBytes(ZMQ.CHARSET), 0);
                } catch (Exception e) {
                    if (Thread.currentThread().isInterrupted()) {
                        log.info("Listener thread interrupted, exiting.");
                        break;
                    }
                    log.error("Error in ZMQ listener loop: ", e);
                }
            }
        });
        listenerThread.setName("AIBridge-ZMQ-Listener");
        listenerThread.start();
        log.info("AI Bridge ZMQ listener started on tcp://*:5555");
    }

    @Override
    protected void shutDown() throws Exception {
        log.info("AI Bridge shutting down...");
        
        // Close socket first to unblock recv() and allow thread to exit cleanly
        if (socket != null) {
            socket.close();
        }
        
        if (listenerThread != null) {
            listenerThread.interrupt();
            // Give the thread a moment to exit gracefully
            try {
                listenerThread.join(1000); // Wait up to 1 second for thread to finish
            } catch (InterruptedException e) {
                log.warn("Interrupted while waiting for listener thread to finish");
                Thread.currentThread().interrupt(); // Restore interrupted status
            }
        }
        
        if (context != null) {
            context.close(); // Use close() for ZContext
        }
        log.info("AI Bridge ZMQ listener stopped.");
        log.info("AI Bridge stopped!");
    }

    private String handleAction(Map<String, Object> actionDetails) {
        String actionType = (String) actionDetails.get("action_type");
        Map<String, Object> parameters = (Map<String, Object>) actionDetails.get("parameters");

        if (actionType == null) {
            return gson.toJson(Map.of("status", "error", "message", "Missing action_type"));
        }
        if (parameters == null) {
            // Ensure parameters is not null for validation, even if some actions might not need it.
             return gson.toJson(Map.of("status", "error", "message", "Parameters map is null for action: " + actionType));
        }

        // Parameter validation happens BEFORE clientThread.invoke
        switch (actionType.toLowerCase()) {
            case "type_string":
                if (!parameters.containsKey("text") || !(parameters.get("text") instanceof String)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameter 'text' (String) is required for type_string."));
                }
                break;
            case "attack_npc":
                if (!parameters.containsKey("npc_id") || !(parameters.get("npc_id") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameter 'npc_id' (Number) is required for attack_npc."));
                }
                break;
            case "interact_object":
                if (!parameters.containsKey("object_id") || !(parameters.get("object_id") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameter 'object_id' (Number) is required for interact_object."));
                }
                // "action" is optional String
                if (parameters.containsKey("action") && !(parameters.get("action") instanceof String)) {
                     return gson.toJson(Map.of("status", "error", "message", "Optional parameter 'action' must be a String for interact_object."));
                }
                break;
            case "interact_inventory":
                if (!parameters.containsKey("item_id") || !(parameters.get("item_id") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameter 'item_id' (Number) is required for interact_inventory."));
                }
                // "action" is optional String
                 if (parameters.containsKey("action") && !(parameters.get("action") instanceof String)) {
                     return gson.toJson(Map.of("status", "error", "message", "Optional parameter 'action' must be a String for interact_inventory."));
                }
                break;
            case "click_widget":
                if (!parameters.containsKey("widget_id") || !(parameters.get("widget_id") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameter 'widget_id' (Number) is required for click_widget."));
                }
                // "child_id" is optional Number
                if (parameters.containsKey("child_id") && !(parameters.get("child_id") instanceof Number)) {
                     return gson.toJson(Map.of("status", "error", "message", "Optional parameter 'child_id' must be a Number for click_widget."));
                }
                break;
            case "walk_to":
                if (!parameters.containsKey("x") || !(parameters.get("x") instanceof Number) ||
                    !parameters.containsKey("y") || !(parameters.get("y") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameters 'x' (Number) and 'y' (Number) are required for walk_to."));
                }
                // "plane" is optional Number
                if (parameters.containsKey("plane") && !(parameters.get("plane") instanceof Number)) {
                     return gson.toJson(Map.of("status", "error", "message", "Optional parameter 'plane' must be a Number for walk_to."));
                }
                break;
            case "interact_ground_item":
                if (!parameters.containsKey("item_id") || !(parameters.get("item_id") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Parameter 'item_id' (Number) is required for interact_ground_item."));
                }
                // Optional x, y, plane for specific ground item targeting
                if ((parameters.containsKey("x") && !(parameters.get("x") instanceof Number)) ||
                    (parameters.containsKey("y") && !(parameters.get("y") instanceof Number)) ||
                    (parameters.containsKey("plane") && !(parameters.get("plane") instanceof Number))) {
                    return gson.toJson(Map.of("status", "error", "message", "Optional parameters 'x', 'y', 'plane' must be Numbers for interact_ground_item."));
                }
                break;
            case "invoke_menu_action_detailed":
                if (!parameters.containsKey("option") || !(parameters.get("option") instanceof String) ||
                    !parameters.containsKey("target") || !(parameters.get("target") instanceof String) ||
                    !parameters.containsKey("id")     || !(parameters.get("id") instanceof Number) ||
                    !parameters.containsKey("opcode") || !(parameters.get("opcode") instanceof Number) ||
                    !parameters.containsKey("param0") || !(parameters.get("param0") instanceof Number) ||
                    !parameters.containsKey("param1") || !(parameters.get("param1") instanceof Number)) {
                    return gson.toJson(Map.of("status", "error", "message", "Missing or invalid parameters for invoke_menu_action_detailed. Required: option (String), target (String), id (Number), opcode (Number), param0 (Number), param1 (Number)."));
                }
                if (parameters.containsKey("force_left_click") && !(parameters.get("force_left_click") instanceof Boolean)) {
                     return gson.toJson(Map.of("status", "error", "message", "Optional parameter 'force_left_click' must be a Boolean for invoke_menu_action_detailed."));
                }
                break;
            default:
                 return gson.toJson(Map.of("status", "error", "message", "Unknown action_type: " + actionType));
        }

        final Map<String, Object> finalParameters = parameters;
        clientThread.invoke(() -> {
            try {
                // Logic within clientThread.invoke now assumes parameters are valid types if they reached here.
                // However, the values themselves might be invalid (e.g. non-existent ID).
                switch (actionType.toLowerCase()) {
                    case "type_string":
                        String textToType = (String) finalParameters.get("text");
                        keyboardTypeString(textToType);
                        log.info("Submitted type_string: " + textToType);
                        break;
                    case "attack_npc":
                        int npcIdToAttack = ((Number) finalParameters.get("npc_id")).intValue();
                        NPC npcToAttack = findNpcById(npcIdToAttack);
                        if (npcToAttack != null) {
                            interactWithNpc(npcToAttack, "Attack");
                            log.info("Submitted attack_npc: " + npcIdToAttack);
                        } else {
                            log.warn("NPC not found for attack: " + npcIdToAttack + ". Action not performed.");
                        }
                        break;
                    case "interact_object":
                        int objectIdToInteract = ((Number) finalParameters.get("object_id")).intValue();
                        String objectAction = (String) finalParameters.getOrDefault("action", "Interact");
                        TileObject objectToInteract = findTileObjectById(objectIdToInteract);
                        if (objectToInteract != null) {
                            interactWithTileObject(objectToInteract, objectAction);
                            log.info("Submitted interact_object: " + objectIdToInteract + " with action: " + objectAction);
                        } else {
                            log.warn("Object not found for interaction: " + objectIdToInteract + ". Action not performed.");
                        }
                        break;
                    case "interact_inventory":
                        int itemIdToInteract = ((Number) finalParameters.get("item_id")).intValue();
                        String itemAction = (String) finalParameters.getOrDefault("action", "Use");
                        interactWithInventoryItem(itemIdToInteract, itemAction);
                        log.info("Submitted interact_inventory: " + itemIdToInteract + " with action: " + itemAction);
                        break;
                    case "click_widget":
                        int widgetId = ((Number) finalParameters.get("widget_id")).intValue();
                        int childId = ((Number) finalParameters.getOrDefault("child_id", -1)).intValue();
                        clickWidgetWrapper(widgetId, childId);
                        log.info("Submitted click_widget: " + widgetId + (childId != -1 ? "." + childId : ""));
                        break;
                    case "walk_to":
                        int x = ((Number) finalParameters.get("x")).intValue();
                        int y = ((Number) finalParameters.get("y")).intValue();
                        int plane = ((Number) finalParameters.getOrDefault("plane", client.getPlane())).intValue();
                        WorldPoint targetPoint = new WorldPoint(x, y, plane);
                        walkToWrapper(targetPoint);
                        log.info("Submitted walk_to: " + targetPoint);
                        break;
                    case "interact_ground_item":
                        int itemIdToPickup = ((Number) finalParameters.get("item_id")).intValue();
                        interactWithGroundItem(itemIdToPickup, finalParameters);
                        log.info("Submitted interact_ground_item for item ID: " + itemIdToPickup);
                        break;
                    case "invoke_menu_action_detailed":
                        String option = (String) finalParameters.get("option");
                        String targetDetailedName = (String) finalParameters.get("target");
                        int idDetailed = ((Number) finalParameters.get("id")).intValue();
                        int opcodeDetailed = ((Number) finalParameters.get("opcode")).intValue();
                        int param0Detailed = ((Number) finalParameters.get("param0")).intValue();
                        int param1Detailed = ((Number) finalParameters.get("param1")).intValue();
                        boolean forceLeftClick = false;
                        if (finalParameters.containsKey("force_left_click") && finalParameters.get("force_left_click") instanceof Boolean) {
                            forceLeftClick = (Boolean) finalParameters.get("force_left_click");
                        }
                        MenuAction menuAction = MenuAction.of(opcodeDetailed);
                        client.menuAction(param0Detailed, param1Detailed, menuAction, idDetailed, -1, option, targetDetailedName);
                        log.info("Executed invoke_menu_action_detailed: option=" + option + ", target=" + targetDetailedName + ", id=" + idDetailed + ", opcode=" + opcodeDetailed + ", param0=" + param0Detailed + ", param1=" + param1Detailed + ", forceLeftClick=" + forceLeftClick);
                        break;
                    // No default here as unknown action_types are caught before clientThread.invoke
                }
            } catch (Exception e) {
                // This catch block is for unexpected errors during action execution on the client thread.
                log.error("Error executing action on client thread: " + actionType, e);
                // Note: The ZMQ reply has already been sent as "submitted" at this point.
                // True outcome reporting would require a more complex async mechanism.
            }
        });
        return gson.toJson(Map.of("status", "submitted", "action_type", actionType));
    }

    private void keyboardTypeString(String text) {
        // This is a placeholder. True keyboard input is complex and might require java.awt.Robot
        // or direct event dispatching if the client API supports it.
        // For now, we'll log it. A possible workaround could be to send a chat message.
        log.info("Placeholder: keyboardTypeString called with text: " + text);
        // Example of sending a chat message if that's an acceptable substitute:
        // client.runScript(ScriptID.SEND_CHAT_MESSAGE, text, 0); // This is just an example, actual script might differ
    }

    private NPC findNpcById(int npcId) {
        for (NPC npc : client.getNpcs()) {
            if (npc.getId() == npcId) {
                return npc;
            }
        }
        return null;
    }

    private TileObject findTileObjectById(int objectId) {
        Player localPlayer = client.getLocalPlayer();
        if (localPlayer == null) {
            log.warn("findTileObjectById: Local player is null, cannot search for object " + objectId);
            return null;
        }

        // Iterate over all tiles in the current scene plane
        Tile[][][] tiles = client.getScene().getTiles();
        int currentPlane = client.getPlane();
        if (currentPlane < 0 || currentPlane >= tiles.length) {
            log.warn("findTileObjectById: Invalid plane " + currentPlane);
            return null;
        }

        for (int x = 0; x < tiles[currentPlane].length; x++) {
            for (int y = 0; y < tiles[currentPlane][x].length; y++) {
                Tile tile = tiles[currentPlane][x][y];
                if (tile == null) {
                    continue;
                }

                // Search GameObjects
                for (GameObject gameObject : tile.getGameObjects()) {
                    if (gameObject != null && gameObject.getId() == objectId) {
                        return gameObject;
                    }
                }

                // Search WallObjects
                WallObject wallObject = tile.getWallObject();
                if (wallObject != null && wallObject.getId() == objectId) {
                    return wallObject;
                }

                // Search GroundObjects
                GroundObject groundObject = tile.getGroundObject();
                if (groundObject != null && groundObject.getId() == objectId) {
                    return groundObject;
                }

                // Search DecorativeObjects
                DecorativeObject decorativeObject = tile.getDecorativeObject();
                if (decorativeObject != null && decorativeObject.getId() == objectId) {
                    return decorativeObject;
                }
            }
        }
        log.warn("TileObject with ID " + objectId + " not found in scene.");
        return null;
    }

    private void interactWithNpc(NPC npc, String action) {
        final String targetName = npc.getName() != null ? npc.getName() : "NPC";
        // The opcode for NPC interactions can vary. NPC_FIRST_OPTION to NPC_FIFTH_OPTION,
        // or specific ones like NPC_SECOND_OPTION for Attack.
        MenuAction menuAction = MenuAction.NPC_FIRST_OPTION; // Default
        if ("Attack".equalsIgnoreCase(action)) {
            menuAction = MenuAction.NPC_SECOND_OPTION; // Attack is typically second option
        }
        
        // Use the correct client.menuAction API
        client.menuAction(npc.getIndex(), 0, menuAction, npc.getId(), -1, action, targetName);
        log.info("Attempted interaction with NPC " + npc.getId() + " (" + targetName + "), Action: " + action + ", Opcode: " + menuAction.getId());
    }

    private void interactWithTileObject(TileObject tileObject, String action) {
        // Get object name through ObjectComposition
        String targetName = null;
        ObjectComposition objectComp = client.getObjectDefinition(tileObject.getId());
        if (objectComp != null) {
            targetName = objectComp.getName();
        }
        if (targetName == null || targetName.trim().isEmpty() || targetName.equals("null")) {
            targetName = "<col=ffff>" + tileObject.getId();
        }
        
        MenuAction menuActionType = MenuAction.GAME_OBJECT_FIRST_OPTION; // Default

        if (tileObject instanceof GameObject) {
            menuActionType = MenuAction.GAME_OBJECT_FIRST_OPTION; // Or SECOND, THIRD etc. based on 'action'
        } else if (tileObject instanceof WallObject) {
            menuActionType = MenuAction.GAME_OBJECT_FIRST_OPTION; // WallObject uses same actions as GameObject
        } else if (tileObject instanceof GroundObject) {
            menuActionType = MenuAction.GAME_OBJECT_FIRST_OPTION; // GroundObject uses same actions as GameObject  
        } else if (tileObject instanceof DecorativeObject) {
            menuActionType = MenuAction.GAME_OBJECT_FIRST_OPTION; // DecorativeObject uses same actions as GameObject
        }
        
        // Use the correct client.menuAction API
        client.menuAction(tileObject.getLocalLocation().getSceneX(), tileObject.getLocalLocation().getSceneY(), 
                         menuActionType, tileObject.getId(), -1, action, targetName);
        log.info("Attempted interaction with TileObject " + tileObject.getId() + " (" + targetName + "), Action: " + action + ", Opcode: " + menuActionType.getId());
    }

    private void interactWithInventoryItem(int itemId, String action) {
        ItemContainer inventory = client.getItemContainer(InventoryID.INVENTORY);
        if (inventory == null) {
            log.warn("Inventory not found for item interaction: " + itemId);
            return;
        }
        Item itemToInteract = null;
        int itemSlot = -1;
        Item[] items = inventory.getItems();
        for (int i = 0; i < items.length; i++) {
            if (items[i].getId() == itemId) {
                itemToInteract = items[i];
                itemSlot = i;
                break;
            }
        }
        if (itemToInteract != null) {
            // Get item name through ItemComposition
            String targetName = null;
            ItemComposition itemComp = client.getItemDefinition(itemToInteract.getId());
            if (itemComp != null) {
                targetName = itemComp.getName();
            }
            if (targetName == null || targetName.trim().isEmpty()) {
                targetName = "Item " + itemToInteract.getId();
            }
            
            // Use CC_OP for component operations (inventory items)
            MenuAction menuAction = MenuAction.CC_OP;
            
            // Use the correct client.menuAction API
            client.menuAction(itemSlot, InventoryID.INVENTORY_CONTAINER, menuAction, 1, itemToInteract.getId(), action, targetName);
            log.info("Attempted interaction with inventory item " + itemToInteract.getId() + " (" + targetName + "), Action: " + action + ", Slot: " + itemSlot);
        } else {
            log.warn("Item with ID " + itemId + " not found in inventory");
        }
    }

    private void clickWidgetWrapper(int groupId, int childId) {
        Widget widget;
        if (childId == -1) {
            // If childId is -1, usually means the parent widget itself if it's clickable,
            // or a specific default child. client.getWidget(groupId) may not be what we want.
            // Typically, a clickable element has both group and child.
            // We might fetch client.getWidget(groupId) and see if it's valid.
            // For now, let's assume a valid childId is usually provided, or it's a specific known widget.
            widget = client.getWidget(groupId); // This gets the parent widget
            if (widget == null || widget.getChildren() == null || widget.getChildren().length == 0) {
                 // If it's a simple widget without children or we intend to click the root.
                 log.info("clickWidgetWrapper: childId is -1, targeting widget group " + groupId);
            } else {
                // Heuristic: if childId is -1 and parent has children, maybe default to first child or specific one?
                // This area is tricky without more context on how widget_id without child_id is used.
                // For now, if childId is -1, we'll use the parent widget directly.
                log.info("clickWidgetWrapper: childId is -1, targeting widget group " + groupId + ". If it has children, this might not be the intended click target.");
            }
        } else {
            widget = client.getWidget(groupId, childId);
        }

        if (widget != null && !widget.isHidden()) {
            String actionName = (widget.getActions() != null && widget.getActions().length > 0) ? widget.getActions()[0] : "Select";
            // param0 is often -1 or widget.getIndex() for CC_OP, param1 is widget.getId() (packed)
            // identifier can be related to menu index or item id if applicable.
            int identifier = widget.getItemId() != -1 ? widget.getItemId() : 1; // Default or item id
            int param0 = widget.getIndex(); // Often -1 for non-list widgets, or actual index.

            MenuEntry menuEntry = client.createMenuEntry(actionName, widget.getName(), identifier, MenuAction.CC_OP.getId(), param0, widget.getId(), false);
            client.invokeMenuAction(menuEntry.getOption(), menuEntry.getTarget(), menuEntry.getIdentifier(), menuEntry.getOpcode(), menuEntry.getParam0(), menuEntry.getParam1());
            log.info("Attempted click on widget Group: " + groupId + ", Child: " + childId + " (WidgetID: " + widget.getId() + "), Action: " + actionName + ", Opcode: " + MenuAction.CC_OP.getId());
        } else {
            log.warn("Widget Group: " + groupId + ", Child: " + childId + " not found or hidden.");
        }
    }

    private void walkToWrapper(WorldPoint point) {
        // param0 is sceneX, param1 is sceneY. Identifier (3rd param) is typically 0 for "Walk here".
        MenuEntry menuEntry = client.createMenuEntry("Walk here", "", 0, MenuAction.WALK.getId(), point.getX() - client.getBaseX(), point.getY() - client.getBaseY(), false);
        client.invokeMenuAction(menuEntry.getOption(), menuEntry.getTarget(), menuEntry.getIdentifier(), menuEntry.getOpcode(), menuEntry.getParam0(), menuEntry.getParam1());
        log.info("Attempted to walk to " + point);
    }
    
    private void interactWithGroundItem(int itemId, Map<String, Object> parameters) {
        // This method is invoked from handleAction, which is already on clientThread.
        Player localPlayer = client.getLocalPlayer();
        if (localPlayer == null) {
            log.warn("Local player is null, cannot interact with ground item.");
            return;
        }

        TileItem targetItem = null;

        if (parameters.containsKey("x") && parameters.containsKey("y") && parameters.containsKey("plane")) {
            try {
                int x = ((Number) parameters.get("x")).intValue();
                int y = ((Number) parameters.get("y")).intValue();
                int plane = ((Number) parameters.get("plane")).intValue();
                WorldPoint specificLocation = new WorldPoint(x, y, plane);
                
                Tile specificTile = getTileFromWorldPoint(specificLocation);
                if (specificTile != null) {
                    List<TileItem> itemsOnTile = specificTile.getGroundItems();
                    if (itemsOnTile != null) {
                        for (TileItem item : itemsOnTile) {
                            if (item != null && item.getId() == itemId) {
                                targetItem = item;
                                log.info("Found specific ground item by coordinates: ID " + itemId + " at " + specificLocation);
                                break;
                            }
                        }
                    }
                }
            } catch (Exception e) {
                log.error("Error parsing specific coordinates for ground item interaction: ", e);
            }
        }

        if (targetItem == null) { // Fallback to closest if not found at specific location or no coords given
            log.info("Specific ground item not found or no coords given, searching for closest item ID: " + itemId);
            double minDistance = Double.MAX_VALUE;
            Tile[][][] sceneTiles = client.getScene().getTiles();
            int z = client.getPlane();

            if (sceneTiles != null && z >= 0 && z < sceneTiles.length && z < Constants.MAX_Z) { 
                for (int tileX = 0; tileX < Constants.SCENE_SIZE; ++tileX) {
                    for (int tileY = 0; tileY < Constants.SCENE_SIZE; ++tileY) {
                        Tile tile = sceneTiles[z][tileX][tileY];
                        if (tile == null) continue;
                        List<TileItem> itemsOnTile = tile.getGroundItems();
                        if (itemsOnTile != null) {
                            for (TileItem item : itemsOnTile) {
                                if (item != null && item.getId() == itemId) {
                                    double distance = item.getTile().getWorldLocation().distanceTo(localPlayer.getWorldLocation());
                                    if (distance < minDistance) {
                                        minDistance = distance;
                                        targetItem = item;
                                    }
                                }
                            }
                        }
                    }
                }
            }
             if (targetItem != null) {
                log.info("Found closest ground item: ID " + itemId + " at " + targetItem.getTile().getWorldLocation() + " with distance " + minDistance);
            }
        }


        if (targetItem != null) {
            String action = "Take"; // Default action
            String targetName = null;
            ItemComposition itemComp = client.getItemDefinition(targetItem.getId());
            if (itemComp != null) {
                targetName = itemComp.getName();
            }
            if (targetName == null || targetName.trim().isEmpty()) targetName = "Item";


            log.info("Attempting to " + action + " item: " + targetItem.getId() + " (" + targetName + ") at " + targetItem.getTile().getWorldLocation());
            MenuEntry menuEntry = client.createMenuEntry(action, targetName, targetItem.getId(), MenuAction.GROUND_ITEM_FIRST_OPTION.getId(), targetItem.getTile().getLocalLocation().getSceneX(), targetItem.getTile().getLocalLocation().getSceneY(), false);
            client.invokeMenuAction(action, targetName, targetItem.getId(), MenuAction.GROUND_ITEM_FIRST_OPTION.getId(), menuEntry.getParam0(), menuEntry.getParam1());
        } else {
            log.warn("Ground item with ID " + itemId + " not found for interaction.");
        }
    }
    
    // Helper to get Tile, as client.getTile() is not a public API method
    private Tile getTileFromWorldPoint(WorldPoint point) {
        if (client.getPlane() != point.getPlane()) {
            return null;
        }
        Tile[][][] tiles = client.getScene().getTiles();
        int x = point.getX() - client.getBaseX();
        int y = point.getY() - client.getBaseY();
        if (x >= 0 && x < Constants.SCENE_SIZE && y >= 0 && y < Constants.SCENE_SIZE) {
            return tiles[point.getPlane()][x][y];
        }
        return null;
    }
}
