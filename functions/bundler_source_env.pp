# Derive the Bundler source credential environment variable name from a gem source URL.
#
# @param source The gem source URL
# @return [String] The Bundler environment variable name
#
function nest::bundler_source_env(String[1] $source) >> String[1] {
  if $source =~ /\A[a-z][a-z0-9+\-.]*:\/\/(?:[^@\/]+@)?([^\/:?#]+)/ {
    $host = $1
  } else {
    fail("Failed to derive Bundler source environment variable from '${source}'")
  }

  "BUNDLE_${upcase(regsubst(regsubst($host, '-', '___', 'G'), '\.', '__', 'G'))}"
}
