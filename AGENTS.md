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
- `pdk validate`: required validation command (syntax, lint, metadata, style).
- `pdk test unit --parallel`: required unit test command (omit `--verbose`).
- Do not substitute validation/testing commands (for example `bundle exec rake ...` or `pdk bundle exec rspec`) unless explicitly requested by the user for troubleshooting.

## Shipping Workflow
- When the user says "ship it", run this sequence unless they explicitly request otherwise:
- `pdk validate`
- `pdk test unit --parallel`
- `git add` and commit with the repository commit style (include a body for larger/new-feature commits).
- `git push`
- `bolt plan run nest::puppet::deploy`

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
- Base classes under `manifests/base/` are private; prefer validating them via `nest` class inclusion/relationship tests.
- If a private base class has fact-driven branching/guard behavior that needs direct assertions, add a dedicated class spec (for example `spec/classes/nest_base_<name>_spec.rb`) with focused expectations only.
- For `on_supported_os`-driven example groups, use targeted RuboCop disables only when required (for example `RSpec/EmptyExampleGroup`).

## Private Base Classes
- Classes under `manifests/base/` are private implementation details of `nest`.
- Private base classes should not expose parameters.
- If configurability is needed, expose it sparingly on `class nest` (`manifests/init.pp`) and let `nest` wire private classes internally.

## Custom Facts
- Custom facts do not need project namespacing; simple fact names are preferred.
- When a custom fact controls branching behavior, add spec coverage for the key states so expected resources are explicitly enforced.

## Commit & Pull Request Guidelines
- Follow observed commit style: `<scope>: <imperative summary>`.
- For larger commits and new features, include a commit message body describing intent and key changes.
- Never construct multiline commit messages with quoted `-m` strings.
- For any multiline commit message (including `--amend`), use a single-quoted heredoc or file and pass it with `git commit -F <file>`.
- Do not use literal `\n` escapes in commit messages.
- Do not use unescaped backticks in shell-quoted commit message text.
- Keep commits scoped; include related test updates.
- PRs/MRs should include a summary, affected paths/classes/plans, tests run, and issues.

## Security & Configuration Tips
- Do not commit plaintext secrets in `data/`, `inventory.yaml`, or plan inputs; use encrypted/CI-managed values.
- Review Bolt plans/scripts before execution; tasks mutate hosts/resources.
