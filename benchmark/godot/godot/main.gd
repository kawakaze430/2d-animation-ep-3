extends Node2D
## Godot Sprite2D + AnimationPlayer renderer proof.
## All pixels use EXACT SAME synthetic rig PNGs and PRECOMPUTED Python Episode03
## IK transforms. This is a graphics-backend benchmark, not native Godot IK.
const FPS := 24.0
const FRAME_COUNT := 360

var animation_player: AnimationPlayer
var rendered_frames := 0

func _abort(reason: String) -> void:
    push_error("Godot renderer fixture validation failed: " + reason)
    get_tree().quit(1)

func _read_json(path: String) -> Variant:
    var raw := FileAccess.get_file_as_string(path)
    if raw.is_empty():
        _abort("Missing or empty " + path)
        return null
    return JSON.parse_string(raw)

func _ready() -> void:
    var fixture := ""
    for argument in OS.get_cmdline_user_args():
        if argument.begins_with("--fixture="):
            fixture = argument.trim_prefix("--fixture=")
    if fixture.is_empty():
        _abort("Provide -- --fixture=/absolute/path")
        return
    var doc = _read_json(fixture.path_join("motion.json"))
    if not doc is Dictionary:
        _abort("motion.json is not a JSON object")
        return
    if int(doc.get("fps", 0)) != 24 or int(doc.get("duration", 0)) != 15:
        _abort("Expected 24 fps and 15 seconds")
        return
    var frames: Array = doc.get("frames", [])
    var parts: Array = doc.get("parts", [])
    if frames.size() != FRAME_COUNT or parts.size() != 15:
        _abort("Expected exactly 360 frames and 15 sprites")
        return

    var background := ColorRect.new()
    background.name = "Background"
    background.color = Color("#e8e1d3")
    background.position = Vector2.ZERO
    background.size = Vector2(960, 540)
    add_child(background)

    var nodes: Array = []
    for index in range(parts.size()):
        var part: Dictionary = parts[index]
        var path: String = fixture.path_join("art").path_join(str(part["file"]))
        var image := Image.new()
        if image.load(path) != OK:
            _abort("Unable to load source sprite " + path)
            return
        var sprite := Sprite2D.new()
        sprite.name = "bone_" + str(index)
        sprite.texture = ImageTexture.create_from_image(image)
        sprite.centered = false
        var pivot: Array = part["pivot"]
        sprite.offset = Vector2(-float(pivot[0]), -float(pivot[1]))
        sprite.texture_filter = CanvasItem.TEXTURE_FILTER_LINEAR
        add_child(sprite)
        nodes.append(sprite)

    animation_player = AnimationPlayer.new()
    animation_player.name = "AnimationPlayer"
    animation_player.root_node = NodePath("..")
    add_child(animation_player)
    var animation := Animation.new()
    animation.length = 15.0
    animation.loop_mode = Animation.LOOP_NONE
    for index in range(parts.size()):
        var target := "bone_" + str(index)
        var position_track := animation.add_track(Animation.TYPE_VALUE)
        animation.track_set_path(position_track, NodePath(target + ":position"))
        var rotation_track := animation.add_track(Animation.TYPE_VALUE)
        animation.track_set_path(rotation_track, NodePath(target + ":rotation_degrees"))
        var scale_track := animation.add_track(Animation.TYPE_VALUE)
        animation.track_set_path(scale_track, NodePath(target + ":scale"))
        for frame_index in range(FRAME_COUNT):
            var values: Dictionary = frames[frame_index][index]
            var pos: Array = values["position"]
            var seconds := float(frame_index) / FPS
            animation.track_insert_key(position_track, seconds, Vector2(float(pos[0]), float(pos[1])))
            animation.track_insert_key(rotation_track, seconds, float(values["rotation_degrees"]))
            var factor := float(values["scale"])
            animation.track_insert_key(scale_track, seconds, Vector2(factor, factor))
    var library := AnimationLibrary.new()
    if library.add_animation("shared_reach", animation) != OK:
        _abort("Cannot register shared_reach AnimationPlayer clip")
        return
    if animation_player.add_animation_library("", library) != OK:
        _abort("Cannot register AnimationPlayer library")
        return
    animation_player.play("shared_reach")
    animation_player.pause()
    animation_player.seek(0.0, true)

func _process(_delta: float) -> void:
    if animation_player == null:
        return
    if rendered_frames >= FRAME_COUNT:
        get_tree().quit()
        return
    # Exact shot-local action pose; Movie Maker's --fixed-fps forces frame stepping.
    animation_player.seek(float(rendered_frames) / FPS, true)
    rendered_frames += 1
