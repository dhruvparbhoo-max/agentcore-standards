// Tool limits for human-approval. Cedar is default-deny.
//
// Shape copied from aws-samples/sample-agentcore-enterprise-platform
// control-library/cedar/gateway-default/10-permit-read-tools.cedar (Apache-2.0).
//
// AgentCore action name format:  AgentCore::Action::"<TargetName>___<tool_name>"
// {{GATEWAY_ARN}} is replaced at deploy time; no ARN is committed.
//
// submit_change still pauses for a person. Cedar says the tool exists;
// approval says when it runs.

permit(
  principal,
  action == AgentCore::Action::"changes___submit_change",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
);
