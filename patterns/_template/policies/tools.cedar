// Tool limits for this pattern. Cedar is default-deny: a tool with no permit is denied.
//
// Shape copied from aws-samples/sample-agentcore-enterprise-platform
// control-library/cedar/gateway-default/10-permit-read-tools.cedar (Apache-2.0).
//
// AgentCore action name format:  AgentCore::Action::"<TargetName>___<tool_name>"
// (three underscores between the gateway target name and the tool name).
// {{GATEWAY_ARN}} is replaced at deploy time; no ARN is committed.
//
// Add one permit per tool in pattern.yaml tools.from_registry. Do not permit a bare
// `action` (every tool). A send, spend, delete, or change tool still pauses for a
// person; Cedar limits which tools exist for this agent, approval limits when they run.
//
// The template lists no tools, so it permits none.
