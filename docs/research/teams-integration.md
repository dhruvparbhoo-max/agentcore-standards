# Making an AgentCore agent available in Microsoft Teams

Researched 9 Oct 2026. Every link below was fetched or seen in search results. Dates are given where the page shows one.

## Short answer

There is no official AWS sample that connects AgentCore Runtime to Teams. AWS has an official Slack sample for AgentCore (March 2026) and an older Teams gateway for Amazon Q Business. The Teams pattern is well covered by an AWS re:Post article, a few community posts, and Microsoft's own docs. Every Teams bot has to be registered with Azure Bot Service, even when the code runs on AWS. Teams then posts each message to an HTTPS endpoint you host, which can be API Gateway plus Lambda.

## Best references

1. AWS ML blog, "Integrating Amazon Bedrock AgentCore with Slack", 23 Mar 2026.
   https://aws.amazon.com/blogs/machine-learning/integrating-amazon-bedrock-agentcore-with-slack/
   Code: https://github.com/aws-samples/sample-Integrating-Amazon-Bedrock-AgentCore-with-Slack
   Official CDK sample. Three Lambdas (verify and ack, queue, agent worker) plus an SQS FIFO queue to beat Slack's 3 second limit. Session ID comes from the Slack thread, actor ID from the Slack user, and AgentCore Memory keeps history. The post says the Slack layer "works unchanged" for any AgentCore agent. This is the closest AWS template to copy for Teams.

2. AWS re:Post, "Microsoft Teams App - DevOps Agent Bi-directional Integration" (no date shown; uses AWS DevOps Agent, so 2026).
   https://repost.aws/articles/ARQwkZ3w1zT82RTkSqnLLdJQ/microsoft-teams-app-devops-agent-bi-directional-integration
   Full working Teams build on AWS. API Gateway HTTP API, an events Lambda that checks the Bot Framework JWT and replies within 3 seconds, an async worker Lambda (up to 15 minutes), and a notify Lambda fired by EventBridge that posts results back to the same thread later. Includes Python code, token handling, the Teams manifest, a per-channel routing table and an AWS cost estimate of about $2 a month. Note: it registers the bot as multi-tenant, which Microsoft no longer allows for new bots.

3. AIThinkers, "Salesforce to Teams on AWS: Building an Escalation Agent with Amazon Bedrock AgentCore", 20 Jul 2026.
   https://www.aithinkers.com/insights/salesforce-teams-escalation-agent-aws-bedrock-agentcore
   Community post. Splits a push path (scheduled notifier posts a card to a channel) from a pull path (@mention goes through Azure Bot Service to a ~200 line bridge Lambda, then to AgentCore). The bridge checks the token, acks at once, strips the @mention and gives each Teams conversation its own agent session. Uses the free Azure Bot tier. Compares this with Copilot Studio.

4. aws-samples, "spec-driven-presentation-maker", Teams and Slack integration guide.
   https://github.com/aws-samples/sample-spec-driven-presentation-maker/blob/main/docs/en/teams-slack-integration.md
   Short AWS sample doc showing the bot handler calling AgentCore Runtime directly at POST /runtimes/{arn}/invocations with a JWT bearer token and reading the SSE stream. Says the Teams handler is the same as the Slack one, with Bot Framework parsing swapped in.

5. aws-samples, "amazon-q-teams-gateway".
   https://github.com/aws-samples/amazon-q-teams-gateway
   Older official Teams bot for Amazon Q Business, deployed by CloudFormation. Uses a single-tenant bot and says not to enable the streaming endpoint. Useful for its setup steps, but Amazon Q Business now shows "no longer open to new customers" in its docs (Amazon Quick replaces it), so it's not a base to build on.

6. Microsoft Learn, "Stream agent messages" (Teams).
   https://learn.microsoft.com/en-us/microsoftteams/platform/bots/streaming-ux
   Streaming is generally available but only in one-on-one chats, one stream per chat at a time, about 1 request per second, and the stream must finish within two minutes. Advice is to buffer model tokens for 1.5 to 2 seconds.

7. Microsoft, ProxyAgent sample for the Microsoft 365 Agents Toolkit.
   https://github.com/OfficeDev/microsoft-365-agents-toolkit-samples/tree/dev/ProxyAgent-NodeJS
   Microsoft's own pattern for putting any outside AI backend into Teams and Microsoft 365 Copilot. The proxy handles transport, SSO and streaming, and you swap one file for the backend call. Node.js and hosted on Azure, but it's the official shape of a "custom engine agent".

8. Microsoft Learn, "Register a Bot Framework bot with Azure".
   https://learn.microsoft.com/en-us/azure/bot-service/bot-service-quickstart-registration?view=azure-bot-service-4.0
   Confirms a bot hosted outside Azure just needs an Azure Bot resource pointing at its web address. New multi-tenant bots were blocked after 31 July 2025; use single-tenant or a user-assigned managed identity. Local data residency is offered in West Europe and Central India.

Other useful pages:
- Azure Bot Service pricing: Teams is a standard channel with unlimited free messages on both Free and S1 tiers. Premium channels (custom Direct Line and Web Chat) are $0.50 per 1,000 after 10,000 free. https://azure.microsoft.com/en-us/pricing/details/bot-services/
- Bot Framework long-running operations: the service times out after 10 to 15 seconds with a 504, so long work must run in the background and reply with a proactive message. https://learn.microsoft.com/en-us/azure/bot-service/bot-builder-howto-long-operations-guidance?view=azure-bot-service-4.0
- Proactive messages in Teams (bot must be installed for the user or team, and you store the conversation ID; Graph can install the app for a user). https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/conversations/send-proactive-messages
- Teams bot SSO: works in one-on-one and group chats, not in channels; token exchange goes through the Bot Framework token service. https://learn.microsoft.com/en-us/microsoftteams/platform/bots/how-to/authentication/bot-sso-overview
- Entra on-behalf-of flow, for swapping the user's token for a Graph token. https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow
- Universal Actions for Adaptive Cards (Action.Execute, refresh per user, up to 60 user IDs). Good fit for approval cards. https://learn.microsoft.com/en-us/microsoftteams/platform/task-modules-and-cards/cards/universal-actions-for-adaptive-cards/work-with-universal-actions-for-adaptive-cards
- Bot Service regionalization: the regional bot only covers Bot Service data; Teams and other services can still move data outside the region; host your code in the same region for end-to-end residency. https://learn.microsoft.com/en-us/azure/bot-service/bot-builder-concept-regionalization?view=azure-bot-service-4.0
- Publishing custom apps: users submit, a Teams admin publishes in Teams admin center > Manage apps; permission and setup policies control who gets it. https://learn.microsoft.com/en-us/microsoftteams/submit-approve-custom-apps
- AgentCore Runtime inbound JWT authorizer (can trust Entra ID tokens). https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html and the Entra example https://github.com/awslabs/agentcore-samples/blob/main/06-workshops/03-AgentCore-identity/08-IDP-examples/EntraID/README.md
- AgentCore Gateway has a built-in Microsoft Teams target (Graph: list chats and channels, send messages, read meeting transcripts). That's for an agent acting on Teams as a tool, not for users chatting with the agent. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-integrations.html
- Microsoft 365 Developer blog, "Building Agents for Teams", 16 Jul 2026. Microsoft now pushes the "Teams SDK" (TypeScript, C#, Python) with MCP, agent-to-agent, Adaptive Cards and Graph built in. https://devblogs.microsoft.com/microsoft365dev/building-agents-for-teams-turning-conversations-into-outcomes/
- Custom engine agents overview (Agents SDK vs Teams SDK vs Copilot Studio). https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/overview-custom-engine-agent

Not a fit for this job:
- Amazon Q Developer in chat applications (formerly AWS Chatbot) supports Teams, but it's for AWS ops: SNS alerts into channels, AWS CLI commands and chatting with Q Developer. It can't front your own agent. https://docs.aws.amazon.com/chatbot/latest/adminguide/teams-setup.html
- Amazon Q Business Teams app and connector: closed to new customers.
- AWS Industries blog on Bedrock and Teams conversations is about indexing Teams data for search, not a bot pattern. https://aws.amazon.com/blogs/industries/how-amazon-bedrock-transforms-microsoft-teams-conversations-into-actionable-insights/

## Recommended architecture

Teams client -> Azure Bot Service (single-tenant Azure Bot resource, Teams channel on, West Europe for EU residency) -> API Gateway HTTP API on AWS (eu-west-2) -> ingress Lambda -> SQS FIFO -> worker Lambda -> AgentCore Runtime (InvokeAgentRuntime, streaming) -> reply posted back to Teams through the Bot Connector API using the stored serviceUrl and conversation ID.

1. Ingress Lambda checks the Bot Framework JWT (keys from login.botframework.com, audience = bot app ID), drops bot echoes, strips the @mention, stores the conversation reference, sends a short "working on it" message or opens a stream, puts the job on SQS and returns 200 within a few seconds.
2. Worker Lambda calls AgentCore Runtime with sessionId = Teams conversation ID (plus thread root ID in channels) and actorId = the user's Entra object ID (aadObjectId). For short answers in one-on-one chat it streams using the Teams streaming API; otherwise it sends one final message.
3. Long or background jobs (ambient pattern) finish later and post a proactive message to the saved conversation, the same way as re:Post's notify Lambda.
4. Approvals post an Adaptive Card with Action.Execute buttons. The click arrives as an invoke activity on the same endpoint, the ingress Lambda checks the clicker is an allowed approver, resumes the paused job, and updates the card so everyone sees the result.
5. Bot app ID and secret (or certificate) live in Secrets Manager. Outbound replies use a client-credentials token for https://api.botframework.com/.default from the tenant-specific Entra endpoint.

## Identity and auth

- Inbound: validate the Bot Framework token on every request. Optionally put a Lambda or JWT authorizer and WAF in front.
- Who the user is: the activity carries the user's aadObjectId and tenant ID. Check the tenant ID matches yours. That's enough to map to an AgentCore actor and to apply per-user rules.
- Acting as the user (for Graph mail or calendar): use Teams SSO with an OAuth connection on the Azure Bot, then exchange for a Graph token with the on-behalf-of flow. SSO works in personal and group chats but not channels. Then pass the user token to AgentCore Identity or a Gateway target. AgentCore Runtime can also accept Entra ID tokens directly through its inbound JWT authorizer.
- Agent acting as itself on Teams (posting alerts, reading channels): the AgentCore Gateway Microsoft Teams target over Graph with app permissions, which needs admin consent.

## Gotchas

- Azure is unavoidable. You need an Azure subscription and an Entra app registration even though the agent runs on AWS. The Azure Bot resource itself is free for Teams.
- New multi-tenant bots are blocked since 31 Jul 2025. Use single-tenant. The managed identity option only helps if the bot code runs in Azure, so on AWS use single-tenant with a secret or certificate. Many older guides (including re:Post) still show multi-tenant.
- Timeouts: Bot Service times out after 10 to 15 seconds. Ack fast and do the work in the background. Lambda's 15 minute cap and AgentCore's 8 hour session cap still apply.
- Streaming only works in one-on-one chats, one stream at a time, about 1 update per second, and the whole stream must end within two minutes. Use plain messages in channels and group chats, and for long jobs.
- Proactive messages only work where the app is installed and you've stored the conversation reference. For people who never opened the bot, the app must be installed for them (Graph or admin setup policy).
- In channels the bot normally only sees messages that @mention it (from Microsoft's channel conversation docs seen in search; not fetched in full). Thread replies have their own conversation ID format (";messageid=").
- Dedupe on activity ID to be safe if a request is retried, and split very long replies (re:Post splits at 25,000 characters). I didn't confirm the exact Teams message size limit.
- Publishing: the org usually blocks custom app upload. An admin has to publish the app in Teams admin center and set who can see it. Graph app permissions need admin consent too.
- Data path: Teams (Microsoft 365) -> Bot Service (global or West Europe) -> your AWS region. Regional Bot Service covers only Bot Service data; Microsoft says Teams and other services can still move data outside the region. Messages and Bot Framework tokens also pass through Microsoft's connector endpoints.
- Costs: Bot Service is free for Teams. AWS side for small use is a few dollars a month (re:Post estimate $2.24 for 3,000 messages). Model and AgentCore costs dominate. Teams itself needs Microsoft 365 licences, which you already have.
- Language: the AWS samples are Python; Microsoft's official Teams SDK and Agents SDK support Python too, so the Lambda can use the SDK or raw REST calls like re:Post does.

## How the Slack pattern maps

| Slack (AWS samples) | Teams equivalent |
| --- | --- |
| Signing secret check | Bot Framework JWT check (RS256, Microsoft keys) |
| 3 second ack | 10 to 15 second limit, but ack within a few seconds anyway |
| AgentWatch: async self-invoke (InvocationType Event) | Same, or SQS FIFO as in the AgentCore Slack sample |
| response_url / chat.postMessage | POST {serviceUrl}/v3/conversations/{id}/activities with bot token |
| Thread ts as session ID | Conversation ID (plus message ID for channel threads) |
| Slack user ID as actor ID | Entra aadObjectId |
| Block Kit buttons | Adaptive Card Action.Execute |
| Slack app install | Teams app manifest zip, admin publish |
| Webhook URL for scheduled posts | Stored conversation reference + proactive message |

AgentWatch (sample-ambient-agents-on-agentcore) uses a slash command and replies through response_url after a self-invoke; that maps directly to the ingress plus worker Lambdas above.

## Fit with the pattern library

Add `primitives/channels/` with a shared channel interface (receive message, ack, send reply, stream, send card, handle card action, send proactive) and two adapters: `channels/slack/` (lifted from the AWS Slack sample) and `channels/teams/`. Each adapter brings its own CDK construct in `infra/constructs/` (API Gateway, ingress Lambda, SQS FIFO, worker Lambda, secrets, alarms). Agents never know which chat app they're in.

In each `pattern.yaml`, add a `channels:` section, for example `teams: {scopes: [personal, team], streaming: personal-only, approvals: adaptive-card, sso: false}`.

The human-approval primitive gets a Teams renderer (Adaptive Card with Action.Execute). The ambient pattern uses proactive messages for results. The chat pattern streams in one-on-one chats.

Ship a Teams manifest template and an admin publishing checklist in `docs/`. A short "Azure side" runbook covers the Entra app registration, Azure Bot resource in West Europe and the Teams channel. Azure Bot creation can live in a small Bicep or Terraform file because CDK can't create it.
