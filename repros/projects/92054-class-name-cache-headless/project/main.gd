extends SceneTree
# Names FreshClass directly. Without an import pass this file fails to parse
# ("Identifier "FreshClass" not declared in the current scope") and nothing below runs.


func _init() -> void:
	print("RESULT RESOLVED: FreshClass.answer() = %d" % FreshClass.answer())
	quit()
