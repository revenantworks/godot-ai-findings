extends SceneTree
## Probe: when DirAccess.rename_absolute(from, to) replaces an existing `to` and the move fails,
## is `to` still there?
## Run: godot --headless --path repros -s rename_replace.gd
## Met in Evolution at src/main/atomic_file.gd:17 (and key_bindings.gd:59, main.gd:274): a save's
## tmp is renamed over the last good save. Upstream match: Godot issue 118858.
##
## Godot 4.7.2's Windows rename (drivers/windows/dir_access_windows.cpp, lines 340 to 346) deletes
## an existing target first, then calls MoveFileW. If the move then fails, the old file is gone.
## On Linux and macOS, rename() replaces the target in one step. This probe makes the move fail on
## Windows by holding the source file open (FileAccess opens without delete sharing there).
##
## Verdicts:
##   RESULT REPLACED     the rename worked; `to` holds the new bytes (expected on Linux)
##   RESULT LOST_TARGET  the rename failed AND `to` is gone (the bug; expected on Windows)
##   RESULT FAILED_SAFE  the rename failed and `to` still holds the old bytes (what a fix gives)


func _write(path: String, text: String) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(text)
	f.close()


func _read(path: String) -> String:
	return FileAccess.get_file_as_string(path) if FileAccess.file_exists(path) else "<missing>"


func _init() -> void:
	var dir := OS.get_user_data_dir()
	var target := dir.path_join("rename_replace.dat")
	var tmp := dir.path_join("rename_replace.dat.tmp")
	_write(target, "OLD")
	_write(tmp, "NEW")
	var hold := FileAccess.open(tmp, FileAccess.READ)  # keeps the source busy on Windows
	var err := DirAccess.rename_absolute(tmp, target)
	hold = null
	print("PROBE os=%s rename=%s target=%s tmp=%s" % [OS.get_name(), error_string(err), _read(target), _read(tmp)])
	if err == OK:
		print("RESULT REPLACED: the target holds the new bytes")
	elif _read(target) == "<missing>":
		print("RESULT LOST_TARGET: the rename failed after deleting the target")
	else:
		print("RESULT FAILED_SAFE: the rename failed and the target kept the old bytes")
	DirAccess.remove_absolute(target)
	DirAccess.remove_absolute(tmp)
	quit()
