extends SceneTree
## Probe: a Control outside any Container that grew to meet its minimum size, then had its
## position set, stops shrinking when the minimum drops.
## Run: godot --headless --path repros -s control_position_bake.gd
## Met in Evolution at src/ui/hud.gd:2066 (the left panel ran 30 to 50 px past the window) and
## src/ui/season_notice.gd:473 (a notice panel stuck 1694 px tall).
##
## Control.set_position (scene/gui/control.cpp, line 1482 on 4.7.2) recomputes the offsets from
## the CURRENT size, which the minimum has already stretched. The stretched size is then stored
## as the Control's own size, so a later, smaller minimum no longer shrinks it.
## Case A (no position write) is the control: it tracks its minimum both ways.


func _init() -> void:
	_run.call_deferred()


func _settle() -> void:
	await process_frame
	await process_frame


func _row(tag: String, c: Control) -> String:
	return "PROBE %-26s size.y=%-6s min.y=%-6s offsets=%s..%s" % [tag, c.size.y, c.get_combined_minimum_size().y, c.offset_top, c.offset_bottom]


func _run() -> void:
	var a := Control.new()
	root.add_child(a)
	a.custom_minimum_size = Vector2(10, 200)
	await _settle()
	print(_row("A min 200", a))
	a.custom_minimum_size = Vector2(10, 50)
	await _settle()
	print(_row("A min 50", a))

	var b := Control.new()
	root.add_child(b)
	b.custom_minimum_size = Vector2(10, 200)
	await _settle()
	print(_row("B min 200", b))
	b.position = Vector2(0, 30)
	await _settle()
	print(_row("B position set", b))
	b.custom_minimum_size = Vector2(10, 50)
	await _settle()
	print(_row("B min 50", b))

	if is_equal_approx(a.size.y, 50.0) and is_equal_approx(b.size.y, 200.0):
		print("RESULT STUCK: after set_position, B keeps 200 px with a 50 px minimum; A shrank to 50")
	elif is_equal_approx(b.size.y, 50.0):
		print("RESULT SHRINKS: B follows its minimum down after set_position")
	else:
		print("RESULT OTHER: A=%s B=%s" % [a.size.y, b.size.y])
	quit()
