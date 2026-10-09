// Tool limits for policy Q&A. Cedar is default-deny.
//
// Shape copied from aws-samples/sample-agentcore-enterprise-platform
// control-library/cedar/gateway-default/10-permit-read-tools.cedar (Apache-2.0).
//
// This pattern has no model-picked tools. Retrieve is a trusted wrapper
// (policy_qa.knowledge) that filters by the verified login, then calls the
// Gateway knowledge-base target (locally: agentcore_tools.Corpus). There is
// no search_policies tool, so this file permits none.
