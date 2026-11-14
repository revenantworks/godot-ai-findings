extends SceneTree
## Probe: does ConfigFile report the right line number for a parse error?
## Run: godot --headless --path repros -s configfile_line.gd
## Met in Evolution at tools/check_hud.gd:1334 ("line 3 counted from 0" for a bad 4th line).
##
## Each case puts one bad line ("x = = 1") on a known 1-based line and loads it. The engine's own
## ERROR line names the line it blames; compare it with the PROBE line printed just after it.
## A text resource (.tres) with the same bad line is the control: the same Godot parser family
## reports it 1-based.

const CASES := {
	1: "x = = 1\n",
	2: "[s]\nx = = 1\n",
	4: "[columns]\nversion=1\nshown=[\"baskets\"]\nx = = 1\n",
	6: "[s]\na=1\nb=2\nc=3\nd=4\nx = = 1\n",
}


func _init() -> void:
	for line: int in CASES:
		var path := "user://configfile_line_%d.cfg" % line
		var f := FileAccess.open(path, FileAccess.WRITE)
		f.store_string(CASES[line])
		f.close()
		var err := ConfigFile.new().load(path)
		print("PROBE ConfigFile: bad line is line %d (1-based); load() = %s; the ERROR above should end ':%d:'" % [line, error_string(err), line])
	var tres := "user://configfile_line_control.tres"
	var t := FileAccess.open(tres, FileAccess.WRITE)
	t.store_string("[gd_resource type=\"Resource\" format=3]\n\n[resource]\nmetadata/x = = 1\n")
	t.close()
	var res := ResourceLoader.load(tres)
	print("PROBE control .tres: bad line is line 4 (1-based); loaded = %s; the ERROR above should end ':4 -'" % [res != null])
	print("RESULT read the ERROR lines: ConfigFile on 4.7.2 prints line-1 (':0:' for line 1), the .tres prints the true line")
	quit()
