// Tool limits for ambient. Cedar is default-deny.
//
// Shape copied from aws-samples/sample-agentcore-enterprise-platform
// control-library/cedar/gateway-default/10-permit-read-tools.cedar (Apache-2.0).

permit(
  principal,
  action == AgentCore::Action::"changes___submit_change",
  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"
);
