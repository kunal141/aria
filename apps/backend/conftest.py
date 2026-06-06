# Week scripts are standalone demo scripts, not pytest test suites.
# They use print-based output and run destructive setup at module scope.
# Exclude them from automatic pytest discovery.
collect_ignore_glob = ["week*.py"]
