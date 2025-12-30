import React, { useEffect, useRef, useState } from "react"
import { Row, Modal, ModalBody, ModalHeader } from "components/Containers"
import styled from "styled-components"
import { Box, Button, Dropdown } from "./UIElements"
import { getUrl, setUrl, httppost } from "../backend"
import { ReactComponent as RawUAV } from "icons/uav.svg"
import { ReactComponent as RawUAVbw } from "icons/uav-bw.svg"

const Modes = ["Manual", "Auto", "Loiter", "RTL", "Takeoff", "Land", "Circle", "Stabilize"]

const NavContainer = styled.div`
	background: #FFFFFF;
	border-bottom: 2px solid #E2E8F0;
	display: flex;
	align-items: center;
	justify-content: space-between;
	height: 3.5rem;
	padding: 0 1.5rem;
	box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
`

const Logo = styled.h3`
	margin: 0;
	font-size: 0.95rem;
	font-weight: 700;
	letter-spacing: 0.08em;
	color: #2563EB;
	text-transform: uppercase;
`

const NavCenter = styled.div`
	display: flex;
	align-items: center;
	gap: 2rem;
`

const NavLinks = styled.nav`
	display: flex;
	gap: 1.5rem;
	align-items: center;
`

const StyledLink = styled.a`
	text-decoration: none;
	color: #64748B;
	font-size: 0.8rem;
	font-weight: 600;
	letter-spacing: 0.03em;
	text-transform: uppercase;
	transition: all 0.2s ease;
	position: relative;
	padding: 0.5rem 0;

	&:hover {
		color: #2563EB;
	}
`

const FlightModeSection = styled.div`
	display: flex;
	align-items: center;
	gap: 0.75rem;
	padding: 0.35rem 0.75rem;
	background: #F8FAFC;
	border: 1px solid #E2E8F0;
	border-radius: 6px;
`

const ModeInfo = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
`

const ModeLabel = styled.div`
	font-size: 0.6rem;
	font-weight: 600;
	color: #94A3B8;
	letter-spacing: 0.05em;
	text-transform: uppercase;
`

const ModeDropdown = styled(Dropdown)`
	height: 1.75rem;
	font-size: 0.75rem;
	padding: 0.25rem 0.5rem;
	min-width: 5.5rem;
	background: white;
	border: 1px solid #E2E8F0;
	border-radius: 4px;
	
	button {
		height: 1.75rem;
		font-size: 0.75rem;
		padding: 0.25rem 0.5rem;
		background: white;
		color: #2563EB;
		font-weight: 600;
	}
`

const ArmStatusContainer = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding-left: 0.75rem;
	border-left: 1px solid #E2E8F0;
`

const StatusBadge = styled.div`
	padding: 0.3rem 0.65rem;
	border-radius: 4px;
	font-size: 0.65rem;
	font-weight: 700;
	letter-spacing: 0.03em;
	background: ${props => props.armed ? '#D1FAE5' : '#F1F5F9'};
	color: ${props => props.armed ? '#059669' : '#64748B'};
	border: 1px solid ${props => props.armed ? '#A7F3D0' : '#E2E8F0'};
	white-space: nowrap;
`

const UAV = styled(RawUAV)`
	height: 2.2em;
	width: 3.2em;
	cursor: pointer;
	opacity: 0.9;
	transition: all 0.3s ease;

	&:hover {
		opacity: 1;
		transform: scale(1.08);
	}
`

const UAVbw = styled(RawUAVbw)`
	height: 2.2em;
	width: 3.2em;
	cursor: pointer;
	opacity: 0.5;
	transition: all 0.3s ease;

	&:hover {
		opacity: 0.7;
		transform: scale(1.08);
	}
`

const SettingsButton = styled.button`
	background: white;
	border: 1px solid #E2E8F0;
	border-radius: 6px;
	padding: 0.45rem 0.9rem;
	cursor: pointer;
	color: #2563EB;
	font-size: 0.75rem;
	font-weight: 600;
	letter-spacing: 0.03em;
	text-transform: uppercase;
	transition: all 0.2s ease;
	display: flex;
	align-items: center;
	gap: 0.4rem;

	&:hover {
		background: #F8FAFC;
		border-color: #CBD5E1;
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
	}

	&:active {
		transform: scale(0.98);
	}

	svg {
		width: 14px;
		height: 14px;
	}
`

const SettingsIcon = () => (
	<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
		<circle cx="12" cy="12" r="3"/>
		<path d="M12 1v6m0 6v6M5.64 5.64l4.24 4.24m4.24 4.24l4.24 4.24M1 12h6m6 0h6M5.64 18.36l4.24-4.24m4.24-4.24l4.24-4.24"/>
	</svg>
)

const ModalContent = styled.div`
	display: flex;
	flex-direction: column;
	gap: 1rem;
`

const ModalLabel = styled.div`
	font-size: 0.875rem;
	font-weight: 600;
	color: #6F879E;
	letter-spacing: 0.05em;
	text-transform: uppercase;
	margin-bottom: 0.5rem;
`

const InputRow = styled.div`
	display: flex;
	gap: 0.75rem;
	align-items: flex-end;
`

const ConnectionButton = (props) => {
	const [open, setOpen] = useState(false)
	const boxRef = useRef(null)

	useEffect(() => {
		if (open) {
			boxRef.current?.focus()
		}
	}, [open])

	return (
		<>
			<SettingsButton onClick={() => setOpen(true)}>
				<SettingsIcon />
				Settings
			</SettingsButton>
			<Modal open={open} setOpen={setOpen}>
				<ModalHeader>Backend Connection</ModalHeader>
				<ModalBody>
					<ModalContent>
						<div>
							<ModalLabel>Query URL</ModalLabel>
							<InputRow>
								<Box 
									style={{ flex: 1 }} 
									ref={boxRef} 
									editable={true} 
									content={getUrl()}
								/>
								<Button 
									style={{ height: "2.85rem", minWidth: "8rem" }} 
									onClick={() => {
										setUrl(boxRef.current.value)
										setOpen(false)
									}}
								>
									Set URL
								</Button>
							</InputRow>
						</div>
					</ModalContent>
				</ModalBody>
			</Modal>
		</>
	)
}

const Header = ({ Aarmed = "", Amode = "", setAmode = () => {} }) => {
	return (
		<NavContainer>
			<Logo>Team Sammpaati Ground Station</Logo>
			<NavCenter>
				<NavLinks>
					<StyledLink href="/">Flight Data</StyledLink>
					<StyledLink href="/params">Params</StyledLink>
					<StyledLink href="/submissions">Submissions</StyledLink>
				</NavLinks>
					<ArmStatusContainer>
						<StatusBadge armed={!Aarmed.includes("DISARMED")}>
							{Aarmed.includes("DISARMED") ? "DISARMED" : "ARMED"}
						</StatusBadge>
						{Aarmed.includes("DISARMED") ? 
							<UAVbw onClick={() => httppost("/uav/arm")} title="Disarmed - Click to Arm" /> : 
							<UAV onClick={() => httppost("/uav/disarm")} title="Armed - Click to Disarm" />
						}
					</ArmStatusContainer>
			</NavCenter>
			<ConnectionButton />
		</NavContainer>
	)
}

export { Header }