extends SceneTree
# Loads the derived script by path (so this file compiles whatever happens to the others),
# reports what the engine says about it, then instantiates it and calls into it, own method first,
# inherited method second. A crash ends the process before the RESULT line; probe/run_repro.py
# reads the exit code. A clean refusal prints RESULT REFUSED.


func _init() -> void:
	var derived: Script = load("res://derived.gd")
	print("REPRO loaded derived=%s" % [derived != null])
	if derived == null:
		_finish("REFUSED", "load() returned null")
		return
	print("REPRO can_instantiate=%s base_script=%s" % [derived.can_instantiate(), derived.get_base_script()])
	if not derived.can_instantiate():
		_finish("REFUSED", "can_instantiate() is false")
		return
	var obj: Object = derived.new()
	print("REPRO new() returned %s" % [obj])
	if obj == null:
		_finish("REFUSED", "new() returned null")
		return
	print("REPRO derived_value=%s" % [obj.call("derived_value")])
	print("REPRO base_value=%s" % [obj.call("base_value")])
	_finish("NO_CRASH", "instantiated and called both methods")


func _finish(result: String, detail: String) -> void:
	print("RESULT %s: %s (engine %s)" % [result, detail, Engine.get_version_info().string])
	quit()
