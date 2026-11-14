class_name Base124
extends RefCounted
# Fails to COMPILE under `-s` (it parses fine): `Auto` is an autoload, and a `-s` run compiles
# this before autoloads are known. The typed array member is what the crash reads.

var list: Array[int] = [1, 2, 3]


func touch() -> void:
	print(Auto.name)
