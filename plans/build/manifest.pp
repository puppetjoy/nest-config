# @summary Assemble a multi-arch manifest
#
# @param image Image name
# @param image_tags Tags of the image to add to the manifest
# @param deploy Deploy the manifest
# @param registry Container registry to push to
# @param registry_username Username for registry
# @param registry_password Password for registry
# @param registry_password_var Environment variable for registry password
# @param tag Tag for the manifest
plan nest::build::manifest (
  String            $image,
  Array[String]     $image_tags,
  Boolean           $deploy                = false,
  Boolean           $mirror                = false,
  String            $registry              = lookup('nest::build::registry', default_value => 'localhost'),
  Optional[String]  $registry_username     = lookup('nest::build::registry_username', default_value => undef),
  Optional[String]  $registry_password     = lookup('nest::build::registry_password', default_value => undef),
  String            $registry_password_var = 'NEST_REGISTRY_PASSWORD',
  String            $tag                   = 'latest',
) {
  $image_real = $image.regsubst("^${registry.regexpescape}/", '')

  if $deploy {
    if $registry_username {
      $registry_password_env = system::env($registry_password_var)
      if $registry_password_env {
        $registry_password_real = $registry_password_env
      } elsif $registry_password {
        $registry_password_real = $registry_password
      } else {
        $registry_password_real = prompt('Registry password', 'sensitive' => true).unwrap
      }

      run_command("podman login --username=${registry_username} --password-stdin ${registry} <<< \$registry_password", 'localhost', 'Login to registry', _env_vars => {
        'registry_password' => $registry_password_real,
      })
    }
  }

  if run_command("podman manifest exists ${image_real}:${tag}", 'localhost', "Check if ${image_real}:${tag} manifest exists", '_catch_errors' => true).ok {
    run_command("podman manifest rm ${image_real}:${tag}", 'localhost', "Remove existing ${image_real}:${tag} manifest")
  }

  run_command("podman manifest create ${image_real}:${tag}", 'localhost', "Create ${image_real}:${tag} manifest")

  $image_tags.each |$image_tag| {
    run_command("podman manifest add ${image_real}:${tag} ${registry}/${image_real}:${image_tag}", 'localhost', "Add ${image_tag} to ${image_real}:${tag} manifest")
  }

  if $deploy {
    unless $registry == 'localhost' {
      run_command("podman manifest push --all ${image_real}:${tag} ${registry}/${image_real}:${tag}", 'localhost', "Push ${image_real}:${tag} manifest")
    }

    if $mirror {
      $eyrie_registry_password = lookup('nest::service::registry::admin_password')
      ['registry.eyrie', 'registry-test.eyrie'].each |$r| {
        run_command("podman login --username=admin --password-stdin ${r} <<< \$registry_password", 'localhost', "Login to ${r}", '_env_vars' => {
          'registry_password' => $eyrie_registry_password.unwrap,
        })
        run_command("podman manifest push --all ${image_real}:${tag} ${r}/${image_real}:${tag}", 'localhost', "Push ${image_real}:${tag} manifest to ${r}")
      }
    }
  }
}
