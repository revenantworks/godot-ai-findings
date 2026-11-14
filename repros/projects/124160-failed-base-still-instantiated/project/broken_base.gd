class_name BrokenBase
extends RefCounted
# Fails to compile on purpose: NoSuchClass is never declared. This is the "undeclared class"
# case that Evolution's handoff notes record as dropping the whole script.

var marker := 41


func helper() -> int:
	var thing := NoSuchClass.new()
	return thing.size()


func base_value() -> int:
	return marker + 1
