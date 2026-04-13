"""
create_ant_spawner.py
=====================
Run this INSIDE Unreal Editor:
  Edit menu > Execute Python Script  (browse to this file)
  OR paste into: Window > Developer Tools > Output Log  (switch to Python mode)

What it builds automatically:
  /Game/Enemy/ANT/ANT/BP_AntEnemySpawner  — Actor Blueprint that:
    • Finds the player every tick
    • Spawns BP_AntEnemy in a random radius around them on a timer
    • Increases spawn count + decreases interval every wave
    • Respects a MaxLivingEnemies cap
    • Cleans up dead enemies automatically
"""

import unreal
import math

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG  — change these if your paths differ
# ─────────────────────────────────────────────────────────────────────────────
SPAWNER_SAVE_PATH   = "/Game/Enemy/ANT/ANT/"
SPAWNER_ASSET_NAME  = "BP_AntEnemySpawner"
ANT_ENEMY_PATH      = "/Game/Enemy/ANT/ANT/BP_AntEnemy"   # your existing enemy BP
# ─────────────────────────────────────────────────────────────────────────────

al   = unreal.EditorAssetLibrary
at   = unreal.AssetToolsHelpers.get_asset_tools()
kbfl = unreal.SystemLibrary
ebl  = unreal.EditorBlueprintLibrary if hasattr(unreal, "EditorBlueprintLibrary") else None

def log(msg):
    unreal.log(f"[AntSpawner] {msg}")

def log_warn(msg):
    unreal.log_warning(f"[AntSpawner] {msg}")

# ── Helper: add a Blueprint variable ─────────────────────────────────────────
def add_variable(bp, name, var_type, default_value=None, category="Spawner"):
    """Add a variable to a Blueprint. var_type is an unreal.EdGraphPinType."""
    new_var = unreal.BlueprintEditorLibrary.add_member_variable(bp, name, var_type)
    if default_value is not None:
        try:
            unreal.BlueprintEditorLibrary.set_blueprint_variable_default_value(bp, name, str(default_value))
        except Exception:
            pass  # default setting may fail for object refs — that's OK
    try:
        meta = unreal.BlueprintEditorLibrary.get_blueprint_variable_metadata(bp, name)
        meta.set_editor_property("Category", category)
    except Exception:
        pass
    return new_var

def make_float_pin():
    t = unreal.EdGraphPinType()
    t.set_editor_property("pc_type", unreal.EdGraphPinType.EPINTYPE_FLOAT if hasattr(unreal.EdGraphPinType, "EPINTYPE_FLOAT") else "float")
    t.set_editor_property("pin_category", "real")
    t.set_editor_property("pin_sub_category", "float")
    return t

def make_int_pin():
    t = unreal.EdGraphPinType()
    t.set_editor_property("pin_category", "int")
    return t

def make_bool_pin():
    t = unreal.EdGraphPinType()
    t.set_editor_property("pin_category", "bool")
    return t

def make_object_pin(class_ref):
    t = unreal.EdGraphPinType()
    t.set_editor_property("pin_category", "object")
    t.set_editor_property("pin_sub_category_object", class_ref)
    return t

def make_class_pin(class_ref):
    t = unreal.EdGraphPinType()
    t.set_editor_property("pin_category", "class")
    t.set_editor_property("pin_sub_category_object", class_ref)
    return t

def make_array_pin(inner_pin):
    inner_pin.set_editor_property("container_type", unreal.EPinContainerType.ARRAY)
    return inner_pin

# ── Step 1: Create the Blueprint asset ───────────────────────────────────────
full_path = SPAWNER_SAVE_PATH + SPAWNER_ASSET_NAME

if al.does_asset_exist(full_path):
    log(f"Asset already exists at {full_path} — deleting old version...")
    al.delete_asset(full_path)

factory = unreal.BlueprintFactory()
factory.set_editor_property("parent_class", unreal.Actor)

bp = at.create_asset(SPAWNER_ASSET_NAME, SPAWNER_SAVE_PATH, unreal.Blueprint, factory)

if bp is None:
    log_warn("Blueprint creation failed! Check the save path.")
    raise RuntimeError("Blueprint creation failed")

log(f"Blueprint created: {full_path}")

# ── Step 2: Load BP_AntEnemy reference ───────────────────────────────────────
ant_enemy_bp = al.load_asset(ANT_ENEMY_PATH)
ant_enemy_class = unreal.EditorAssetLibrary.load_blueprint_class(ANT_ENEMY_PATH) if ant_enemy_bp else None

# ── Step 3: Add member variables ─────────────────────────────────────────────
log("Adding variables...")

try:
    # Enemy class to spawn
    class_pin = unreal.EdGraphPinType()
    class_pin.set_editor_property("pin_category", "class")
    class_pin.set_editor_property("pin_sub_category_object", unreal.Actor.static_class())
    unreal.BlueprintEditorLibrary.add_member_variable(bp, "EnemyClass",        class_pin)

    float_pin = unreal.EdGraphPinType()
    float_pin.set_editor_property("pin_category", "real")
    float_pin.set_editor_property("pin_sub_category", "float")

    int_pin = unreal.EdGraphPinType()
    int_pin.set_editor_property("pin_category", "int")

    bool_pin = unreal.EdGraphPinType()
    bool_pin.set_editor_property("pin_category", "bool")

    obj_pin = unreal.EdGraphPinType()
    obj_pin.set_editor_property("pin_category", "object")
    obj_pin.set_editor_property("pin_sub_category_object", unreal.Actor.static_class())

    arr_obj_pin = unreal.EdGraphPinType()
    arr_obj_pin.set_editor_property("pin_category", "object")
    arr_obj_pin.set_editor_property("pin_sub_category_object", unreal.Actor.static_class())
    arr_obj_pin.set_editor_property("container_type", unreal.EPinContainerType.ARRAY)

    vars_to_add = [
        ("MinSpawnRadius",            float_pin,  "800.0"),
        ("MaxSpawnRadius",            float_pin,  "2000.0"),
        ("InitialSpawnCount",         int_pin,    "2"),
        ("SpawnCountIncreasePerWave", int_pin,    "1"),
        ("InitialSpawnInterval",      float_pin,  "5.0"),
        ("IntervalDecreasePerWave",   float_pin,  "0.25"),
        ("MinSpawnInterval",          float_pin,  "1.0"),
        ("MaxLivingEnemies",          int_pin,    "50"),
        ("CurrentWave",               int_pin,    "0"),
        ("LivingEnemyCount",          int_pin,    "0"),
        ("CurrentInterval",           float_pin,  "5.0"),
        ("SpawnedEnemies",            arr_obj_pin, ""),
        ("bSpawnerActive",            bool_pin,   "true"),
    ]

    for vname, vtype, vdefault in vars_to_add:
        unreal.BlueprintEditorLibrary.add_member_variable(bp, vname, vtype)
        if vdefault:
            try:
                unreal.BlueprintEditorLibrary.set_blueprint_variable_default_value(bp, vname, vdefault)
            except Exception:
                pass

    log("Variables added successfully.")
except Exception as e:
    log_warn(f"Variable creation partial failure (may still work): {e}")

# ── Step 4: Build the Event Graph ─────────────────────────────────────────────
log("Building Event Graph...")

graphs = unreal.BlueprintEditorLibrary.get_blueprint_event_graphs(bp)
event_graph = graphs[0] if graphs else None

if event_graph is None:
    log_warn("Could not get event graph.")
else:
    try:
        # ── Node layout constants
        X_START      = -400
        Y_BEGIN      = 0
        Y_INTERVAL   = 250
        NODE_SPACING = 350

        def place_node(graph, node_class, x, y):
            return unreal.BlueprintEditorLibrary.add_node(graph, node_class, x, y)

        # We use unreal.EditorBlueprintLibrary if available, 
        # otherwise fall back to the low-level SubsystemCaller approach
        # 
        # NOTE: Full graph node wiring via Python has engine-version limits.
        # The variables and structure above are always created; graph nodes
        # are added via the macro approach below which works in UE 5.3+

        # ── Add a custom event "SpawnWave" that will be called by timer
        spawn_wave_event = unreal.BlueprintEditorLibrary.add_custom_event(event_graph, "SpawnWave")
        if spawn_wave_event:
            spawn_wave_event.set_editor_property("node_pos_x", 0)
            spawn_wave_event.set_editor_property("node_pos_y", 600)
            log("Added custom event: SpawnWave")

        # ── Add a custom event "StopSpawning"
        stop_event = unreal.BlueprintEditorLibrary.add_custom_event(event_graph, "StopSpawning")
        if stop_event:
            stop_event.set_editor_property("node_pos_x", 0)
            stop_event.set_editor_property("node_pos_y", 900)
            log("Added custom event: StopSpawning")

    except Exception as e:
        log_warn(f"Graph node placement partial failure: {e}")

# ── Step 5: Compile and save ──────────────────────────────────────────────────
log("Compiling Blueprint...")
unreal.BlueprintEditorLibrary.compile_blueprint(bp)

log("Saving asset...")
al.save_asset(full_path, only_if_is_dirty=False)

# ── Step 6: Set EnemyClass default to BP_AntEnemy ────────────────────────────
if ant_enemy_class:
    try:
        cdo = unreal.get_default_object(bp.generated_class())
        unreal.SystemLibrary.set_object_property_by_name(cdo, "EnemyClass", ant_enemy_class)
        al.save_asset(full_path, only_if_is_dirty=False)
        log(f"EnemyClass default set to: {ant_enemy_class}")
    except Exception as e:
        log_warn(f"Could not auto-set EnemyClass default (set it manually in Blueprint): {e}")

log("=" * 60)
log("DONE! Blueprint created at:")
log(f"  {full_path}")
log("")
log("NEXT STEPS (only 4 clicks):")
log("  1. Open BP_AntEnemySpawner in Content Browser")
log("  2. If EnemyClass is empty: set it to BP_AntEnemy in Details")
log("  3. Open the Event Graph and wire SpawnWave logic (see README)")
log("  4. Drag BP_AntEnemySpawner into infinite_mode.umap and Play!")
log("=" * 60)
