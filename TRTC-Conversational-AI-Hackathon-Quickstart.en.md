# TRTC Conversational AI Hackathon Quickstart

Add speech recognition, speech synthesis, or real\-time AI conversation to your hackathon app with TRTC\. This guide walks you through creating an application, gathering credentials, making your first service call, and connecting the results to your app’s workflow\.

## AI Tools &#40;Optional&#41;

If you use AI coding tools, the following resources can help with development\.

### TRTC Skills: Integration and Troubleshooting

[TRTC Skills](https://github.com/Tencent-RTC/agent-skills/blob/main/README.md) provides integration workflows and tools to help inspect your project environment, configure credentials, write integration code, start services, find documentation, and troubleshoot errors\. The current Conversational AI workflows cover **AI customer service, speaking practice, and real\-time translation on Web**\. See the repository for the supported scope\.

Run the following command in your project directory\. The installer automatically detects supported IDEs:

```bash
npx -y @tencent-rtc/trtc-agent-skills@latest add
```

See the [installation instructions](https://github.com/Tencent-RTC/agent-skills/blob/main/README.md#quick-start) for options such as selecting a specific IDE\. After installation, describe the feature you need or the integration issue in your AI coding tool to use the relevant Skills workflow\.

### llms.txt: Find Official Documentation

Give your AI coding tool the [TRTC documentation index](https://trtc.io/llms.txt) as an entry point for finding product documentation.

For Conversational AI, use the [Conversational AI documentation index](https://trtc.io/llms/conversational-ai.txt) to look for product information, SDK integration guides, and API references.

### \.md: Read Individual Documents

For documentation pages that support raw Markdown, AI tools can read the steps, parameters, and code directly\. For example: [Real\-time AI conversation integration guide &#40;Markdown&#41;](https://trtc.io/document/68337.md)\.

For documentation pages that support this format, append `.md` to the path of the regular documentation URL\. For example, `https://trtc.io/document/68337` corresponds to `https://trtc.io/document/68337.md`\.

## 1 Try the Demo

Open the [online demo](https://trtc.io/demo/homepage/#/detail?scene=ai), allow microphone access, say something, and listen to the AI’s response\.

Your app can use the following capabilities:

- **Speech recognition &#40;STT / ASR&#41;**: Convert speech into text for input, subtitles, or further processing\. In this guide, both STT and ASR refer to speech\-to\-text; the integration method depends on your chosen use case\.
- **Speech synthesis &#40;TTS&#41;**: Convert text into audio so your app can read out responses or results\.
- **Real\-time AI conversation**: Connect speech recognition, a large language model &#40;LLM&#41;, and speech synthesis for ongoing conversations\.

Next, integrate using your own application and credentials\. Add only the capabilities your hackathon project needs\.

## 2 Create an Application and Get Credentials

### Create a TRTC Application

1. Register or sign in through the [TRTC registration page](https://trtc.io/register?utm_source=hackathon&utm_term=register&utm_campaign=Singapore%20Hackathon&_channel_track_key=ERjC9rtA), then enter the TRTC Console\.
2. Click **Create Application** and select **Conversational AI** in the dialog\.
3. Enter an **Application Name**, such as `hackathon-app`, and choose a **Deployment Region**\.
4. Click **Create**\. When you reach **Conversational AI Overview**, your application has been created and the capability is activated\.
5. Check the validity period and remaining free allowance in **Package Management** in the console\.

Note: **After creating your application, you can start with the free allowance without purchasing a paid plan\.**

- **Free allowance**: Eligible accounts can receive **10,000 minutes of usage credits per month for one year**, which can offset TRTC real\-time AI conversation, speech recognition &#40;ASR / STT&#41;, and speech synthesis &#40;TTS&#41; usage\.
- **Credit usage**: The allowance is shared across applications under the same account\. Each service uses its own conversion rules; 10,000 credit minutes do not equal 10,000 minutes of AI conversation or speech recognition\.
- **External services**: LLMs and any third\-party services you connect are billed by their respective providers\.

See the [billing guide](https://trtc.io/document/67833) and [free allowance conversion rules](https://trtc.io/document/42735)\.

### Get Application Credentials and API Keys

The required configuration falls into three groups: application credentials, cloud API keys, and model configuration\. Obtain and save the values required for your chosen integration\.

**Application credentials**

|Item            |Purpose                                                                                                                                     |
|----------------|--------------------------------------------------------------------------------------------------------------------------------------------|
|**SDKAppID**    |Identifies your TRTC application; required for real-time AI conversation, ASR, and TTS                                                      |
|**SDKSecretKey**|Application signing key; used for user authentication signatures in real-time AI conversation and authentication with the standalone ASR SDK|

To obtain them:

1. Open **App Management** in the TRTC Console and find the application you created\.
2. Click the application name to open its details, then copy **SDKAppID**\.
3. Reveal and copy **SDKSecretKey**\.

**Cloud API keys — required for real\-time AI conversation and standalone TTS**

|Item         |Purpose                                                                                             |
|-------------|----------------------------------------------------------------------------------------------------|
|**SecretId** |Identifies the cloud API caller; used together with SecretKey                                       |
|**SecretKey**|Signs cloud API requests, including requests to start or stop AI conversations and synthesize speech|

To obtain them:

1. Open the account menu in the upper\-right corner of the TRTC Console and select **Access Keys**\.
2. Click **Create Key** and complete the verification shown on the page\.
3. Copy and save **SecretId** and **SecretKey** from the creation result\. SecretKey is displayed only when it is created\. You can reuse an existing valid key pair if you have already saved it\.

**Model configuration — required only for real\-time AI conversation**

Obtain the following from your chosen model provider so TRTC can access the LLM that generates responses:

- **API Key**: Authenticates requests to the model service\.
- **Model name**: Specifies the model to use\.
- **Endpoint URL**: Specifies the model API endpoint, which must be accessible from TRTC’s cloud service\.

TRTC’s built\-in TTS does not require additional TTS provider credentials\. If you choose a third\-party TTS service, obtain the credentials that provider requires\.

**Store keys securely:** SDKSecretKey is the application key, while SecretKey is the cloud API signing key\. They are not interchangeable\. Keep SDKSecretKey, SecretKey, and model API keys in backend environment variables or a `.env` file\. Add `.env` to `.gitignore`, and keep these keys out of frontend code and public screenshots\.

## 3 Integrate Conversational AI Capabilities

Choose a section below based on your app’s interaction flow, then follow the corresponding official documentation\. Use the application and credentials from Step 2\. Choose the client platform and development tools that suit your project\.

Your app captures user input, displays text, and plays audio\. Your backend stores keys, generates authentication signatures, or calls services\. For real\-time AI conversation, the client sends and receives audio through TRTC\. For standalone ASR / TTS, the backend returns the service results to your app\.

|Use case                                                  |Section                                                       |Official documentation                                                                                |
|----------------------------------------------------------|--------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
|Let users have ongoing voice conversations with AI        |[3.1 Real-time AI Conversation](#31-real-time-ai-conversation)|[Real-time AI conversation integration guide](https://trtc.io/document/68337)                         |
|Convert speech into text for an existing workflow or agent|[3.2 Speech Recognition](#32-speech-recognition)              |[ASR SDK integration guide](https://github.com/Tencent-RTC/trtc-asr-sdk-nodejs/blob/main/README.en.md)|
|Convert existing text into audio for your app to play     |[3.3 Speech Synthesis](#33-speech-synthesis)                  |[TextToSpeech API](https://trtc.io/document/80010)                                                    |

If you use AI coding tools, see [AI Tools &#40;Optional&#41;](#ai-tools-optional)\.

### 3\.1 Real\-time AI Conversation

TRTC connects speech recognition, an LLM, and speech synthesis so users can have ongoing conversations with AI in your app\.

**Get started:** Follow the [real\-time AI conversation integration guide](https://trtc.io/document/68337)\. Choose Web, Android, iOS, or Flutter, then integrate the SDK, capture audio, and implement conversation start and stop\.

**Key integration points:**

- **User and bot authentication**: Generate [UserSig](https://trtc.io/document/35166) on your backend using SDKAppID, SDKSecretKey, and the respective user IDs\. The user’s UserSig lets the client enter the room\. The bot’s UserSig goes in `AgentConfig.UserSig` in the request that starts the conversation\.
- **Model configuration**: Set up [speech recognition](https://trtc.io/document/69592), the [LLM](https://trtc.io/document/68338), and [speech synthesis](https://trtc.io/document/68340)\. The model endpoint must be accessible from TRTC’s cloud service\. TRTC’s built\-in TTS does not require an external TTS account\.
- **Room and conversation target**: Use the same SDKAppID, room ID, and room ID type on the client and backend\. Use different IDs for the user and bot, and set `TargetUserId` to the current user\.
- **Ending the session**: Save the TaskId returned by [StartAIConversation](https://trtc.io/document/64963)\. When the session ends, call [StopAIConversation](https://trtc.io/document/65296), stop audio capture, and leave the room\.

**Success check:** Complete two conversational turns in your app\. When you end the session, both the microphone capture and the backend AI task stop\. To display recognized speech and response text, add [subtitle callbacks](https://trtc.io/document/68333)\.

### 3\.2 Speech Recognition

Convert speech into text and pass it to an existing input field, business workflow, or agent\.

**Get started:** Follow the [ASR SDK integration guide](https://github.com/Tencent-RTC/trtc-asr-sdk-nodejs/blob/main/README.en.md) to install the SDK and configure authentication\. For a single recording, see the [sentence recognition server example](https://github.com/Tencent-RTC/trtc-asr-sdk-nodejs/blob/main/examples/v3-sentence-asr.ts)\. For a continuous audio stream, see the [real\-time stream recognition server example](https://github.com/Tencent-RTC/trtc-asr-sdk-nodejs/blob/main/examples/v3-realtime-asr.ts)\. Both examples use Node\.js to read local audio files; they do not include microphone capture or an app interface\. For other backend languages, use the SDKs linked in the README\.

**Key integration points:**

- **Credentials**: In the linked v3 examples, set `TRTC_ASR_SDK_APP_ID` to your application’s SDKAppID and `TRTC_ASR_SECRET_KEY` to its SDKSecretKey\. Do not use the cloud API SecretKey here\.
- **Audio and language**: Both examples require an engine argument, such as `bigmodel`\. Use `--lang zh`, `--lang en`, or another supported value to specify the recording language\. The examples process PCM audio; the real\-time example uses 16 kHz, 16\-bit, mono PCM\. For your own recordings, match the actual format and sample rate to the API requirements\. Renaming a browser\-generated WebM file to WAV does not convert the audio format\.
- **Recognition results**: Real\-time recognition includes interim and final results\. Use interim results to update the current segment, then append it when finalized to avoid duplicate subtitles\.
- **Connect to your workflow**: Pass the recognized text to your app’s input or processing flow\. Standalone speech recognition does not require an LLM\.

**Success check:** Your backend returns recognized text\. When you say something in the app, the text appears and is used in an actual input or app action\.

### 3\.3 Speech Synthesis

Convert text produced by your app into audio for playback\.

**Get started:** Follow the [TextToSpeech API documentation](https://trtc.io/document/80010)\. Choose the SDK for your backend language and configure request signing, text, voice, and the output audio format\. To play audio as it is generated, use the [TextToSpeechSSE streaming API](https://trtc.io/document/80009)\.

The [official FlowTTS repository](https://github.com/Tencent-RTC/FlowTTS/blob/main/README_EN.md) provides **implementation references** for Python, Node\.js, and Go\. Use the application and credentials from Step 2\. Follow the official documentation for your chosen API when setting the service address &#40;Endpoint&#41;, Region, API Version, and request parameters\.

**Key integration points:**

- **Credentials**: Use SDKAppID and the cloud API SecretId / SecretKey, rather than SDKSecretKey\.
- **Built\-in service**: TRTC’s built\-in TTS does not require an LLM configuration or an external TTS provider account\.
- **Audio playback**: The non\-streaming API returns Base64\-encoded audio\. Decode it on the backend, then return the audio or an accessible audio URL for the client player\. For your first integration, explicitly select WAV or MP3 for playback in a standard player\. Raw PCM requires appropriate playback handling\.
- **Streaming calls**: SSE returns audio chunks\. Decode them in order and feed them into a playback pipeline that supports PCM\. Finish playback after receiving the end marker\.

**Success check:** A user triggers an action in the app and hears the corresponding result spoken aloud\.

## 4 Validate and Continue Building

Complete one full flow in your app: user input → processing → display or audio playback\. Check that:

- **The results work**: Recognized text, synthesized audio, or AI responses meet expectations and are connected to an actual app action\.
- **The state is clear**: Users can see when the app is recording, processing, or finished\. Show clear messages if microphone permission is denied or a service call fails\.
- **The session ends properly**: Stop audio capture when the action ends\. For real\-time conversation, also stop the backend AI task and leave the room\.

Once the basic integration works, you can add subtitles, interruption handling, streaming playback, or business tool calls\. See the [product documentation](https://trtc.io/document/conversational-ai-overview) for implementation details\. If authentication fails, check whether the two types of SecretKey were mixed up and whether the ASR site or cloud API service address is correct\. If the AI does not respond, check the room ID, room ID type, and TargetUserId\.

## Technical Support

If you run into integration issues, ask in the [hackathon Telegram support group](https://t.me/+qJ54BYg8DeI0OTA1)\. Dedicated technical support staff will help with integration and troubleshooting\. Include your client platform, a description of the issue, error codes, and TaskId / RequestId if available so the team can investigate\.

## 5 Explore Other TRTC Products

TRTC also offers products for messaging, calls, meetings, live streaming, and notifications. Choose the capability your hackathon app needs and follow its quick start.

| Product | What it adds to your app | Quick start |
| --- | --- | --- |
| **Chat** | One-to-one and group messaging, with support for text, images, and files. | [Chat UIKit quick start (React)](https://trtc.io/document/50055) |
| **Call** | In-app voice and video calls using ready-made calling UI components. | [Call quick start (Web)](https://trtc.io/document/60415?menulabel=uikit&platform=web&product=call) |
| **Room / Conference** | Multi-user audio and video rooms with screen sharing and participant management. | [Room quick start (Web)](https://trtc.io/document/60441?platform=web&product=conference) |
| **Live** | Interactive video live streaming and voice chat rooms, with audience chat, co-hosting, and gifts. | [Live streaming quick start (Web / Vue)](https://trtc.io/document/73741) |
| **RTC Engine** | Core audio and video APIs for building a custom real-time experience. | [RTC Engine quick start (Web)](https://trtc.io/document/35607?menulabel=sdk&platform=web&product=rtcengine) |
| **Push** | App push notifications, including offline notifications for mobile users. | [Push quick start (Mobile)](https://trtc.io/document/67555?menulabel=core+sdk&platform=android&product=push) |
