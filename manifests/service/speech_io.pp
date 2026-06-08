class nest::service::speech_io (
  Hash[String, Hash] $stt_instances = {},
  Hash[String, Hash] $tts_instances = {},
) {
  $stt_instances.each |$instance, $attributes| {
    nest::lib::whisper_server { $instance:
      * => $attributes,
    }
  }

  $tts_instances.each |$instance, $attributes| {
    nest::lib::tts_server { $instance:
      * => $attributes,
    }
  }
}
