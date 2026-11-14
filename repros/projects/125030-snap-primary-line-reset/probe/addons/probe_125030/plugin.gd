@tool
extends EditorPlugin
# Opens the 2D editor's Configure Snap dialog, types a new value into each spin box row
# (Grid Offset, Grid Step, Primary Line Every), leaves the field, and reports whether the
# typed value was kept. Two ways to leave: a Tab key event pushed into the dialog window,
# and focus moved to another field (the "click elsewhere" path in the report). Enter, which the
# report says keeps the value, runs once at the end as a control.
# Prints one RESULT line: RESET, KEPT or NOT_DRIVEN. Project-side probe only, no engine change.
# PROBE_DUMP=1 prints the dialog's control tree first.

const ROWS := ["Grid Offset", "Grid Step", "Primary Line Every"]


func _enter_tree() -> void:
	_run.call_deferred()


func _run() -> void:
	await _frames(30)
	EditorInterface.set_main_screen_editor("2D")
	await _frames(10)

	var dialog := _find_snap_dialog(EditorInterface.get_base_control())
	if dialog == null:
		_finish("NOT_DRIVEN", "Configure Snap dialog not found")
		return
	dialog.popup_centered()
	await _frames(10)
	if not dialog.visible:
		_finish("NOT_DRIVEN", "Configure Snap dialog did not open")
		return
	if OS.has_environment("PROBE_DUMP"):
		_dump(dialog, 0)

	var rows := {}
	for row: String in ROWS:
		var boxes := _row_spin_boxes(dialog, row)
		if boxes.size() != 2:
			_finish("NOT_DRIVEN", "row '%s' has %d spin boxes, expected 2" % [row, boxes.size()])
			return
		rows[row] = boxes

	var resets := []
	var tally := 0
	for how: String in ["tab", "focus"]:
		for row: String in ROWS:
			for i in 2:
				var box: SpinBox = rows[row][i]
				var before := box.value
				var typed := before + 3.0
				var after := await _type_and_leave(dialog, box, typed, how)
				var kept := is_equal_approx(after, typed)
				tally += 1
				print("PROBE leave=%s row=%s %s before=%s typed=%s after=%s -> %s" % [
					how, row, "xy"[i], before, typed, after, "KEPT" if kept else "RESET"])
				if not kept:
					resets.append("%s %s by %s" % [row, "xy"[i], how])

	# Control from the report: Enter instead of Tab keeps the value. Runs last, since Enter
	# may also confirm and close the dialog. Reported only, not part of the RESULT verdict.
	var primary_x: SpinBox = rows["Primary Line Every"][0]
	var enter_before := primary_x.value
	var enter_after := await _type_and_leave(dialog, primary_x, enter_before + 3.0, "enter")
	print("PROBE leave=enter row=Primary Line Every x before=%s typed=%s after=%s -> %s" % [
		enter_before, enter_before + 3.0, enter_after,
		"KEPT" if is_equal_approx(enter_after, enter_before + 3.0) else "RESET"])

	if resets.is_empty():
		_finish("KEPT", "all %d fields kept the typed value" % tally)
	else:
		_finish("RESET", "%d of %d fields reset: %s" % [resets.size(), tally, ", ".join(resets)])


# Types `value` into the spin box's LineEdit as text, as a user would, then leaves the field.
func _type_and_leave(dialog: Window, box: SpinBox, value: float, how: String) -> float:
	var line := box.get_line_edit()
	line.grab_focus()
	await _frames(2)
	line.select_all()
	line.delete_text(0, line.text.length())
	line.insert_text_at_caret(String.num(value))  # "4", not "4.0": what a user types
	await _frames(2)
	if how == "tab" or how == "enter":
		var code := KEY_TAB if how == "tab" else KEY_ENTER
		for pressed: bool in [true, false]:
			var key := InputEventKey.new()
			key.keycode = code
			key.physical_keycode = code
			key.pressed = pressed
			dialog.push_input(key)
			await _frames(2)
		if how == "tab" and line.has_focus():
			print("PROBE warning: Tab did not move focus out of the field")
	else:
		dialog.get_ok_button().grab_focus()
		await _frames(2)
	await _frames(3)
	return box.value


func _find_snap_dialog(root: Node) -> Window:
	if root is ConfirmationDialog and root.title == "Configure Snap":
		return root
	for child: Node in root.get_children():
		var hit := _find_snap_dialog(child)
		if hit != null:
			return hit
	return null


# The dialog lays rows out in GridContainers: a Label, then that row's two SpinBoxes.
func _row_spin_boxes(root: Node, row: String) -> Array[SpinBox]:
	var found: Array[SpinBox] = []
	for label: Label in _all_labels(root):
		if not label.text.begins_with(row):
			continue
		var parent := label.get_parent()
		var index := label.get_index()
		for j in range(index + 1, parent.get_child_count()):
			var next := parent.get_child(j)
			if next is Label:
				break
			if next is SpinBox:
				found.append(next)
		return found
	return found


func _all_labels(root: Node) -> Array[Label]:
	var found: Array[Label] = []
	if root is Label:
		found.append(root)
	for child: Node in root.get_children():
		found.append_array(_all_labels(child))
	return found


func _dump(node: Node, depth: int) -> void:
	var extra := ""
	if node is Label:
		extra = " text=%s" % node.text
	elif node is SpinBox:
		extra = " value=%s text=%s" % [node.value, node.get_line_edit().text]
	print("PROBE tree %s%s%s" % ["  ".repeat(depth), node.get_class(), extra])
	for child: Node in node.get_children():
		_dump(child, depth + 1)


func _frames(count: int) -> void:
	for _i in count:
		await get_tree().process_frame


func _finish(result: String, detail: String) -> void:
	print("RESULT %s: %s (engine %s)" % [result, detail, Engine.get_version_info().string])
	get_tree().quit(0)
