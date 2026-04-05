import { NextRequest, NextResponse } from "next/server";
import { AccessToken, RoomAgentDispatch } from "livekit-server-sdk";

const API_KEY = process.env.LIVEKIT_API_KEY || "devkey";
const API_SECRET = process.env.LIVEKIT_API_SECRET || "secret";

export async function GET(request: NextRequest) {
  const voice = "unmute-prod-website/p329_022.wav";
  const identity = `user-${Math.random().toString(36).substring(7)}`;
  const roomName = `unmute-builder-${Math.random().toString(36).substring(7)}`;

  const token = new AccessToken(API_KEY, API_SECRET, {
    identity,
    ttl: "1h",
  });
  token.addGrant({
    room: roomName,
    roomJoin: true,
    roomCreate: true,
    canPublish: true,
    canSubscribe: true,
    agent: true,
  });

  // Dispatch the builder agent by name
  token.roomConfig = {
    agents: [
      {
        agentName: "unmute-livekit-agent-builder",
      } as RoomAgentDispatch,
    ],
    metadata: JSON.stringify({ voice }),
  };

  const jwt = await token.toJwt();

  // Generate Cloudflare TURN credentials for external connectivity
  let iceServers = null;
  const turnTokenId = process.env.CF_TURN_TOKEN_ID;
  const turnApiToken = process.env.CF_TURN_API_TOKEN;
  if (turnTokenId && turnApiToken) {
    try {
      const turnResp = await fetch(
        `https://rtc.live.cloudflare.com/v1/turn/keys/${turnTokenId}/credentials/generate`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${turnApiToken}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ ttl: 86400 }),
        }
      );
      if (turnResp.ok) {
        const turnData = await turnResp.json();
        iceServers = turnData.iceServers;
      }
    } catch (e) {
      console.error("Failed to get TURN credentials:", e);
    }
  }

  return NextResponse.json({ token: jwt, iceServers });
}
