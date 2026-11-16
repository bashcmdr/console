# Contract catalog, not execution results. Context-dependent expectations remain
# unbound until a runner supplies the required fixture and its exact oracle.
def row($argv; $class; $exit; $requires):
  {argv:$argv, command:("bcm" + (if ($argv|length) == 0 then "" else " " + ($argv|map(@sh)|join(" ")) end)),
   classification:$class, expected_exit_code:$exit,
   expectation_kind:(if $exit == null then "fixture_required" else "contract" end),
   requirements:$requires};
def ok($a): row($a; "valid"; 0; []);
def bad($a): row($a; "invalid"; 1; []);
def fixture($a; $r): row($a; "valid"; null; $r);
def stub($a): row($a; "valid"; 1; ["phase1_not_implemented"]);

["poweron","poweroff","status","shortcut","reset","upgrade","uninstall","log"] as $console |
["install","uninstall","upgrade","plug","unplug","quarantine","release","show","list","search","deps","plan","graph","why","diagnose"] as $cartridge |
["sync","list","status"] as $registry |
["install","uninstall","plug","unplug","quarantine","release","show","deps","plan","graph","why","diagnose"] as $named |
[
  ([], ["version"], ["help"], ["-h"], ["--help"] | ok(.)),
  fixture(["doctor"]; ["state_integrity"]),
  (("-h","--help") as $flag |
    ok(["version",$flag]), ok(["help",$flag]), fixture(["doctor",$flag]; ["state_integrity"])),
  (["console","cartridge","registry"][] as $noun |
    ([$noun], [$noun,"help"], [$noun,"-h"], [$noun,"--help"], ["help",$noun] | ok(.))),
  ok(["help","alias"]),
  ({noun:"console",verbs:$console}, {noun:"cartridge",verbs:$cartridge}, {noun:"registry",verbs:$registry} |
    . as $group | $group.verbs[] as $verb |
    (ok(["help",$group.noun,$verb]),
     (("-h","--help") as $flag | ok([$group.noun,$verb,$flag])))),
  ($console[] as $verb |
    if $verb == "upgrade" or $verb == "uninstall" then stub(["console",$verb])
    else fixture(["console",$verb]; ["console_state_and_permissions"]) end),
  stub(["console","upgrade","--force"]), stub(["console","uninstall","--keep-config"]),
  fixture(["console","shortcut","--install"]; ["ordinary_bin_and_shortcut_state"]),
  ("0","1","50" | fixture(["console","log","--lines",.]; ["boot_log"])),
  bad(["console","log","--lines"]), bad(["console","log","--lines",""]),
  bad(["console","log","--lines","-1"]), bad(["console","log","--lines","abc"]),
  bad(["console","shortcut","--force"]), bad(["console","shortcut","--install","extra"]),
  ($named[] as $verb | bad(["cartridge",$verb])),
  ($named[] as $verb |
    fixture(["cartridge",$verb,"nonexistent-cartridge"]; ["absence_and_dependency_state"])),
  ($names[] as $name | $named[] as $verb |
    fixture(["cartridge",$verb,$name]; ["cartridge:"+$name,"operation:"+$verb])),
  ($names[] as $name |
    fixture(["cartridge","uninstall",$name,"--purge"]; ["installed_relationships_and_state"]),
    fixture(["cartridge","quarantine",$name,"manual reason"]; ["installed_state"]),
    fixture(["cartridge","install",$name,"--from","https://example.invalid/fixture.git"]; ["operator_selected_local_repository_fixture"]),
    stub(["cartridge","upgrade",$name])),
  fixture(["cartridge","install","--from","https://example.invalid/fixture.git"]; ["operator_selected_local_repository_fixture"]),
  bad(["cartridge","install","--from"]), bad(["cartridge","install","--from",""]),
  stub(["cartridge","upgrade","--all"]), bad(["cartridge","upgrade"]),
  ("all","active","inactive","quarantine","broken","outdated" | ok(["cartridge","list",.])),
  ok(["cartridge","list"]), bad(["cartridge","list","unknown-filter"]),
  ([[],["--installed"],["--active"],["--installed","--active"]][] as $selector |
    ([[],["python"],["^Demo$"],["quoted\"term"],["path\\\\bin"]][] as $keyword |
      ([[],["--tag","blue"],["--author","Author \"quoted\""],["--tag","blue","--author","Author"]][] as $filters |
        fixture(["cartridge","search"] + $keyword + $selector + $filters;
                ["registry_or_selected_local_manifests"])))),
  ("--tag","--author" | bad(["cartridge","search",.]), bad(["cartridge","search",.,""])),
  bad(["cartridge","search","["]), bad(["cartridge","search","--tag","["]),
  fixture(["cartridge","why","nonexistent-cartridge"]; ["all_installed_dependency_manifests"]),
  fixture(["registry","list"]; ["registry_index"]), fixture(["registry","status"]; ["registry_index_state"]),
  stub(["registry","sync"]),
  fixture(["alias"]; ["alias_store"]), fixture(["alias","list"]; ["alias_store"]),
  fixture(["alias","sample-shortcut","console status"]; ["writable_alias_store"]),
  fixture(["alias","remove","sample-shortcut"]; ["alias_store_membership"]),
  fixture(["alias","remove","nonexistent"]; ["alias_store_membership"]),
  bad(["alias","remove"]), bad(["alias","sample-shortcut"]),
  bad(["invalid-noun"]), bad(["quarantine","demo"]),
  (["console","cartridge","registry"][] | bad([.,"invalid-verb"]))
] |
group_by(.argv) |
map(if ([.[].classification]|unique|length) != 1 or ([.[].expected_exit_code]|unique|length) != 1
    then error("conflicting command expectations")
    else .[0] + {requirements:([.[].requirements[]]|unique)} end) |
sort_by(.argv) | to_entries | map(.value + {id:(.key+1)}) as $rows |
{metadata:{schema:"bashcmdr.command-catalog.v2", grammar:"bcm [noun] verb [arguments] [flags]",
           execution:"not_executed", fixture_names:$names,
           expectation_contract:"Contract exits assume a usable owned runtime; null exits require fixture binding. Detailed help contracts may reveal separately tracked help gaps.",
           total_combinations:($rows|length),
           fixed_expectations:([$rows[]|select(.expected_exit_code != null)]|length),
           fixture_required:([$rows[]|select(.expected_exit_code == null)]|length)},
 test_matrix:$rows}
