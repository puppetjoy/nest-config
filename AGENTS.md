# Repository Guidelines

## Project Structure & Module Organization
- `manifests/`: Puppet classes by domain (`base/`, `gui/`, `service/`, `host/`, `lib/`, `tool/`, `firmware/`).
- `data/`: Hiera data by scope (`host/`, `platform/`, `cluster/`, `kubernetes/`, `build/`, `arch/`).
- `plans/`: Bolt plans (`.pp` and `.yaml`) for build and deploy tasks.
- `functions/` and `lib/`: Puppet functions and Ruby extensions (`lib/facter/`, `lib/puppet/provider/`).
- `templates/` and `files/`: config templates (EPP/ERB) and static assets/scripts.
- `spec/`: RSpec-Puppet tests and fixtures.

## Build, Test, and Development Commands
- `bundle install`: install Ruby and test dependencies.
- `bundle exec rake validate`: run Ruby syntax, Puppet syntax, and metadata checks.
- `bundle exec rake lint`: run `puppet-lint` with project rules.
- `bundle exec rake spec` or `bundle exec rake parallel_spec`: run unit tests.
- `pdk validate`: CI-aligned validation.
- `pdk test unit --parallel --verbose`: CI unit-test flow (no generic RSpec arg pass-through).
- `pdk bundle exec rspec --fail-fast`: stop early when many tests fail.

## Coding Style & Naming Conventions
- Use 2-space indentation in Puppet and Ruby files; avoid unrelated formatting churn.
- Keep class/file mapping consistent: `manifests/base/console.pp` defines `nest::base::console`.
- Name specs by target: `spec/classes/<class_path>_spec.rb`, `spec/defines/<define_name>_spec.rb`.
- Follow `.rubocop.yml` for Ruby (`TargetRubyVersion: 2.6`, max line length 200).
- Lint warnings fail by default; honor `.puppet-lint.rc` and existing disabled-check policy.

## PDK-Managed Files
- This module uses PDK templates. Update `.sync.yml` first, then run `pdk update` instead of editing generated files directly.
- In this repo, core template files (`Gemfile`, `Rakefile`, lint/spec config, CI config, and generated spec defaults) are PDK-managed unless marked otherwise.
- If a template file must diverge, set `unmanaged: true` (or `delete: true`) for that file in `.sync.yml` before making manual edits.
- Reference: `pdk-templates` `.sync.yml` docs: https://github.com/puppetlabs/pdk-templates/blob/main/README.md

## Testing Guidelines
- Keep unit tests lightweight: this repo primarily verifies class inclusion/exclusion and key dependency relationships, not full resource behavior.
- Follow the existing pattern in `spec/classes/nest_spec.rb` and `spec/spec_helper_local.rb` (`it_should_and_should_not_contain_classes`) when adding coverage.
- Do not proactively replace lightweight class/relationship specs with deep resource/content assertions unless explicitly requested.
- Add deeper resource/content assertions only when needed to lock down a real regression or critical ordering dependency.
- For broad failures, prefer `pdk bundle exec rspec --fail-fast` over `pdk test unit`; fail-fast is not passed through by `pdk test unit`.

## Commit & Pull Request Guidelines
- Follow observed commit style: `<scope>: <imperative summary>`.
- Keep commits scoped; include related test updates.
- PRs/MRs should include a summary, affected paths/classes/plans, tests run, and issues.

## Security & Configuration Tips
- Do not commit plaintext secrets in `data/`, `inventory.yaml`, or plan inputs; use encrypted/CI-managed values.
- Review Bolt plans/scripts before execution; tasks mutate hosts/resources.
