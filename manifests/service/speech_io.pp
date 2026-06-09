class nest::service::speech_io (
  Hash[String, Hash] $stt_instances = {},
) {
  $stt_instances.each |$instance, $attributes| {
    nest::lib::whisper_server { $instance:
      * => $attributes,
    }
  }
}
