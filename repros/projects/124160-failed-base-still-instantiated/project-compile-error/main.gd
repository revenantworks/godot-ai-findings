extends SceneTree
# Names Derived124 directly, as the reporter's shorter variant does. On 4.7.2 the engine reports
# "Compilation failed" for this file and still runs _initialize. new() returns an object whose
# inherited members were never initialized; iterating `list` then reads a null array.


func _initialize() -> void:
	print("REPRO before new()")
	var d := Derived124.new()
	print("REPRO new() returned %s, list=%s" % [d, d.get("list")])
	for x in d.list:
		print("REPRO item %s" % x)
	print("RESULT NO_CRASH: new() worked and the inherited typed array was iterated")
	quit()
