# Native's existing bounded service role: settings only, never credentials.
type Nest::Wizard = Struct[{
  'enabled'      => Boolean,
  'boards'       => Array[String[1], 0, 100],
  'model'        => Hash[Enum['provider', 'model', 'base_url', 'api_mode'], String[1]],
  'integrations' => Array[String[1]],
}]
