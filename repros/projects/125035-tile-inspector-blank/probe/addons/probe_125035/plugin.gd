@tool
extends EditorPlugin
# Opens res://tileset.tres, picks the Select tool, clicks tile (0, 0), then reports the inspector.
# Prints one RESULT line: FILLED, BLANK or NOT_DRIVEN. Project-side probe only, no engine change.
# With PROBE_SELF_TEST set, it empties the inspector before judging, so a working engine must
# report BLANK. That proves the detector can fail; it says nothing about the engine.


func _enter_tree() -> void:
	_run.call_deferred()


func _run() -> void:
	await _frames(30)
	EditorInterface.edit_resource(load("res://tileset.tres"))
	await _frames(30)

	var atlas_editor := _find_class(EditorInterface.get_base_control(), "TileSetAtlasSourceEditor")
	if atlas_editor == null or not atlas_editor.is_visible_in_tree():
		_finish("NOT_DRIVEN", "atlas editor missing or hidden: %s" % atlas_editor)
		return

	var select_button := _find_tool_button(atlas_editor, "Select")
	if select_button == null:
		_finish("NOT_DRIVEN", "Select tool button not found")
		return
	select_button.button_pressed = true
	select_button.pressed.emit()
	await _frames(5)
	_report(atlas_editor, "after Select tab, before click")

	var atlas_control := _find_gui_input_target(atlas_editor, "_tile_atlas_control_gui_input")
	if atlas_control == null:
		_finish("NOT_DRIVEN", "atlas control not found by its gui_input connection")
		return
	await _click(atlas_control, Vector2(8, 8))
	await _frames(10)

	var tile_inspector := _tile_inspector(atlas_editor)
	if tile_inspector != null and OS.has_environment("PROBE_SELF_TEST"):
		tile_inspector.edit(null)
		await _frames(5)
	_report(atlas_editor, "after click on tile (0, 0)")

	if tile_inspector == null or not tile_inspector.is_visible_in_tree():
		_finish("NOT_DRIVEN", "click selected no tile: the tile inspector never showed")
	elif _property_count(tile_inspector) == 0:
		_finish("BLANK", "tile inspector visible with 0 properties")
	else:
		_finish("FILLED", "tile inspector visible with %d properties" % _property_count(tile_inspector))


func _click(control: Control, local_pos: Vector2) -> void:
	var motion := InputEventMouseMotion.new()
	motion.position = local_pos
	control.gui_input.emit(motion)
	await _frames(2)
	for pressed: bool in [true, false]:
		var button := InputEventMouseButton.new()
		button.button_index = MOUSE_BUTTON_LEFT
		button.pressed = pressed
		button.position = local_pos
		control.gui_input.emit(button)
		await _frames(2)


# The atlas editor holds two inspectors. The other one always edits the source's own proxy.
func _tile_inspector(atlas_editor: Node) -> EditorInspector:
	for inspector: EditorInspector in _find_all_inspectors(atlas_editor):
		var edited := inspector.get_edited_object()
		if edited == null or edited.get_class() != "TileSetAtlasSourceProxyObject":
			return inspector
	return null


func _report(atlas_editor: Node, label: String) -> void:
	print("PROBE --- %s" % label)
	for inspector: EditorInspector in _find_all_inspectors(atlas_editor):
		var edited := inspector.get_edited_object()
		print("PROBE inspector visible=%s edited=%s properties=%d" % [
			inspector.is_visible_in_tree(),
			edited.get_class() if edited else "<null>", _property_count(inspector)])


func _property_count(root: Node) -> int:
	var total := 1 if root is EditorProperty else 0
	for child: Node in root.get_children():
		total += _property_count(child)
	return total


func _find_all_inspectors(root: Node) -> Array[EditorInspector]:
	var found: Array[EditorInspector] = []
	if root is EditorInspector:
		found.append(root)
	for child: Node in root.get_children():
		found.append_array(_find_all_inspectors(child))
	return found


func _find_class(root: Node, target: String) -> Node:
	if root.get_class() == target:
		return root
	for child: Node in root.get_children():
		var hit := _find_class(child, target)
		if hit != null:
			return hit
	return null


func _find_tool_button(root: Node, label: String) -> Button:
	if root is Button and root.toggle_mode and root.button_group != null and (root.text == label or root.tooltip_text == label):
		return root
	for child: Node in root.get_children():
		var hit := _find_tool_button(child, label)
		if hit != null:
			return hit
	return null


func _find_gui_input_target(root: Node, method_name: String) -> Control:
	if root is Control:
		for connection: Dictionary in root.get_signal_connection_list("gui_input"):
			if String(connection.callable.get_method()).contains(method_name):
				return root
	for child: Node in root.get_children():
		var hit := _find_gui_input_target(child, method_name)
		if hit != null:
			return hit
	return null


func _frames(count: int) -> void:
	for _i in count:
		await get_tree().process_frame


func _finish(result: String, detail: String) -> void:
	print("RESULT %s: %s (engine %s)" % [result, detail, Engine.get_version_info().string])
	get_tree().quit(0)
