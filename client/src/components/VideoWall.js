/*
 * VideoWall — a live camera feed from EACH drone (rule 8.14, item 2).
 *
 * Replaces the single MJPEG <img> in VideoFeed.js. Three WebRTC panes served by
 * MediaMTX (scripts/mediamtx.yml) over the mesh. WHIP/WebRTC rather than MJPEG
 * because three MJPEG streams at 480p15 would cost 4.5-6 Mbps and break the
 * link budget; H.264 over WebRTC costs ~0.9 Mbps each.
 *
 * No STUN/TURN. Everything is same-subnet over the mesh, so host ICE candidates
 * are sufficient — and a public STUN server would be an outbound internet call
 * during the mission, breaching rule 8.4.
 */
import { useEffect, useRef, useState } from "react"
import styled from "styled-components"

const Wall = styled.div`
	display: grid;
	grid-template-columns: repeat(${props => props.count}, 1fr);
	gap: 0.4em;
	width: 100%;
`

const Pane = styled.div`
	position: relative;
	background: #111;
	aspect-ratio: 4 / 3;
	overflow: hidden;
	border: 1px solid ${props => (props.live ? "#3a3" : "#633")};
`

const Tag = styled.div`
	position: absolute;
	top: 0;
	left: 0;
	padding: 0.15em 0.5em;
	font-size: 0.75em;
	font-family: monospace;
	background: rgba(0, 0, 0, 0.65);
	color: ${props => (props.live ? "#8f8" : "#f88")};
	z-index: 2;
`

const Video = styled.video`
	width: 100%;
	height: 100%;
	object-fit: cover;
	display: block;
`

/* MediaMTX WHEP endpoint: POST an SDP offer, receive an SDP answer. */
const connect = async (url, video, onState) => {
	const pc = new RTCPeerConnection({ iceServers: [] })
	pc.addTransceiver("video", { direction: "recvonly" })

	pc.ontrack = e => {
		video.srcObject = e.streams[0]
	}
	pc.onconnectionstatechange = () => onState(pc.connectionState)

	const offer = await pc.createOffer()
	await pc.setLocalDescription(offer)

	const res = await fetch(url, {
		method: "POST",
		headers: { "Content-Type": "application/sdp" },
		body: offer.sdp
	})
	if (!res.ok) throw new Error(`WHEP ${res.status}`)
	await pc.setRemoteDescription({ type: "answer", sdp: await res.text() })
	return pc
}

const DroneFeed = ({ droneId, host }) => {
	const videoRef = useRef(null)
	const [state, setState] = useState("connecting")

	useEffect(() => {
		let pc = null
		let retry = null
		let dead = false

		const open = () => {
			if (dead) return
			connect(`http://${host}:8889/drone${droneId}/whep`, videoRef.current, s => {
				setState(s)
				/* A drone dropping off the mesh must not kill the pane; the
				 * operator needs to see it come back. 2 s is below the 10 s
				 * bundle-continuation window, so the feed returns before the
				 * aircraft acts on link loss. */
				if (s === "failed" || s === "disconnected") {
					retry = setTimeout(open, 2000)
				}
			})
				.then(c => {
					pc = c
				})
				.catch(() => {
					setState("offline")
					retry = setTimeout(open, 2000)
				})
		}
		open()

		return () => {
			dead = true
			if (retry) clearTimeout(retry)
			if (pc) pc.close()
		}
	}, [droneId, host])

	const live = state === "connected"
	return (
		<Pane live={live}>
			<Tag live={live}>
				DRONE {droneId} · {live ? "LIVE" : state.toUpperCase()}
			</Tag>
			<Video ref={videoRef} autoPlay muted playsInline />
		</Pane>
	)
}

const VideoWall = ({ drones = [1, 2, 3], host }) => {
	const gcs = host || window.location.hostname
	return (
		<Wall count={drones.length}>
			{drones.map(id => (
				<DroneFeed key={id} droneId={id} host={gcs} />
			))}
		</Wall>
	)
}

export default VideoWall
