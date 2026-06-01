# frozen_string_literal: true

PuppetLint.new_check(:deploy_plan_boundary) do
  DEPLOY_PLAN = %r{^\s*plan\s+\S*deploy\S*\s*\(}
  CONTROL_COMMENT = %r{nest-lint:\s*allow-deploy-pp-plan\s+-\s*\S+}

  def check
    return if control_comment_present?

    manifest_lines.each_with_index do |line, index|
      next unless line.match?(DEPLOY_PLAN)

      notify(
        :error,
        {
          message: 'plans with deploy in the name must be YAML deployment wrappers; add a nest-lint: allow-deploy-pp-plan control comment with a reason only for deliberate imperative exceptions',
          line: index + 1,
          column: line.index('plan') + 1,
        },
      )
    end
  end

  private

  def control_comment_present?
    manifest_lines.any? { |line| line.match?(CONTROL_COMMENT) }
  end
end
