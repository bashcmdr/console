# Current rapid-result records are data; no field is executable or opened as a path.
def integer: type == "number" and isfinite and (isnan | not) and . == floor;
def outcome:
  if .exit_code == .expected_exit then
    if .expected_exit == 0 then "success" else "expected_failure" end
  elif .exit_code == 0 or .exit_code == 1 then "mismatch" else "error" end;
def percentage($n; $d): if $d == 0 then 0 else (($n * 1000 / $d) | floor) / 10 end;
def summarize:
  length as $total
  | (map(select(.classification == "success")) | length) as $success
  | (map(select(.classification == "expected_failure")) | length) as $expected
  | (map(select(.classification == "mismatch")) | length) as $mismatch
  | (map(select(.classification == "error")) | length) as $errors
  | {total:$total,successful:$success,expected_failures:$expected,
     mismatches:$mismatch,errors:$errors,matched:($success+$expected),
     success_percentage:percentage($success;$total),
     expected_percentage:percentage($expected;$total),
     mismatch_percentage:percentage($mismatch;$total),error_percentage:percentage($errors;$total)};
def category:
  (.argv[1:] // []) as $args
  | if ["help","version","doctor","-h","--help"] | index($args[0] // "help") then "Core commands"
    elif $args[0] == "console" then "Console commands"
    elif ($args[0] == "cartridge" or $args[0] == "registry") and $args[1] == "list" then "List commands"
    elif $args[0] == "cartridge" and (["plug","unplug","quarantine","release"] | index($args[1])) then "Cartridge lifecycle"
    elif $args[0] == "cartridge" and $args[1] == "diagnose" then "Provider diagnostics"
    else "Other commands" end;

if length != 1 then error("expected exactly one results document") else .[0] end
| if type != "object" then error("results must be an object") else . end
| if (.metadata | type) != "object" or .metadata.schema != "bashcmdr.rapid-results.v1"
     or (.metadata.executable | type) != "string" or (.metadata.executable | length) == 0
     or (.metadata.case_count | integer | not) or .metadata.case_count < 0
     or (.metadata.generated_at | type) != "string"
     or (.metadata.generated_at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(Z|[+-][0-9]{2}:[0-9]{2})$") | not)
     or (.metadata.duration_clock != null and ((.metadata.duration_clock | type) != "string" or (.metadata.duration_clock | length) == 0))
     or (.metadata.duration_resolution_seconds != null and ((.metadata.duration_resolution_seconds | type) != "number" or (.metadata.duration_resolution_seconds | isfinite | not) or (.metadata.duration_resolution_seconds | isnan) or .metadata.duration_resolution_seconds <= 0))
  then error("unsupported or invalid results metadata") else . end
| if (.results | type) != "array" or (.results | length) != .metadata.case_count
  then error("results do not match metadata case count") else . end
| . as $data
| if all(.results[];
    (.test_id | integer) and .test_id > 0
    and (.argv | type) == "array" and (.argv | length) > 0
    and all(.argv[]; type == "string" and (contains("\u0000") | not))
    and .argv[0] == $data.metadata.executable
    and (.exit_code | integer) and .exit_code >= 0 and .exit_code <= 255
    and (.expected_exit == 0 or .expected_exit == 1)
    and (.passed | type) == "boolean" and .passed == (.exit_code == .expected_exit)
    and .classification == outcome
    and (.duration | type) == "number" and (.duration | isfinite) and (.duration | isnan | not) and .duration >= 0
    and (.output | type) == "string"
    and ((has("command") | not) or (.command | type) == "string"))
    and ([.results[].test_id] | unique | length) == (.results | length)
  then . else error("invalid, duplicate or inconsistent result records") end
| .results as $rows
| ($rows | map(select(.classification == "mismatch" or .classification == "error"))) as $failures
| ($rows | map(.duration)) as $durations
| {schema:"bashcmdr.analysis.v1",source_metadata:.metadata,
   summary:($rows | summarize),
   categories:(reduce ["Core commands","Console commands","List commands","Cartridge lifecycle","Provider diagnostics","Other commands"][] as $name
     ({}; .[$name] = ($rows | map(select(category == $name)) | summarize))),
   coverage:($rows | group_by(.argv[1:]) | map({args:.[0].argv[1:],statistics:summarize})),
   failures:($failures | map({test_id,args:.argv[1:],exit_code,expected_exit,classification,output})),
   patterns:($failures | map(select(.output != "")) | group_by(.output)
     | map({output:.[0].output,count:length}) | sort_by(-.count,.output)),
   timing:{samples:($durations | length),
     average:(if ($durations | length) == 0 then null else ($durations | add / length) end),
     maximum:(if ($durations | length) == 0 then null else ($durations | max) end),
     minimum:(if ($durations | length) == 0 then null else ($durations | min) end),
     clock:(.metadata.duration_clock // "unspecified"),
     resolution_seconds:(.metadata.duration_resolution_seconds // null)},
   slowest:($rows | sort_by(-.duration,.test_id) | .[:5] | map({test_id,args:.argv[1:],duration}))}
