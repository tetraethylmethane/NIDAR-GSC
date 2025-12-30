import { useEffect, useRef, useState } from 'react';
import { getUrl } from './backend';
import styled from "styled-components"

const VideoFeed = () => {
    const [videoError, setVideoError] = useState(false);
    const [isLoading, setIsLoading] = useState(true);
    const videoRef = useRef(null);

    useEffect(() => {
        const img = videoRef.current;
        
        const handleLoad = () => {
            setIsLoading(false);
            setVideoError(false);
        };
        
        const handleError = () => {
            setVideoError(true);
            setIsLoading(false);
        };
        
        if (img) {
            img.addEventListener('load', handleLoad);
            img.addEventListener('error', handleError);
        }
        
        return () => {
            if (img) {
                img.removeEventListener('load', handleLoad);
                img.removeEventListener('error', handleError);
            }
        };
    }, []);

    return (
        <VideoFeedSection>
            <VideoFeedHeader>
                <LiveIndicator />
                <span>LIVE VIDEO FEED</span>
            </VideoFeedHeader>
            <VideoFeedContainer>
                {isLoading && !videoError && (
                    <VideoPlaceholder>
                        <span>Loading camera feed...</span>
                    </VideoPlaceholder>
                )}
                {videoError && (
                    <VideoPlaceholder>
                        <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                            <path d="M23 7l-7 5 7 5V7z"/>
                            <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
                        </svg>
                        <span>Camera feed unavailable</span>
                    </VideoPlaceholder>
                )}
                <img 
                    ref={videoRef}
                    src={`${getUrl()}/video_feed`}
                    alt="Live camera feed"
                    style={{ 
                        width: '100%', 
                        height: '100%', 
                        objectFit: 'contain',
                        display: videoError ? 'none' : 'block'
                    }}
                />
            </VideoFeedContainer>
        </VideoFeedSection>
    );
};


const VideoFeedSection = styled.div`
	display: flex;
	flex-direction: column;
	gap: 0.4rem;
	height: 100%;
`

const VideoFeedHeader = styled.div`
	display: flex;
	align-items: center;
	gap: 0.5rem;
	font-size: 0.7rem;
	font-weight: 600;
	letter-spacing: 0.1em;
	color: #2F6FDB;
`

const LiveIndicator = styled.div`
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: #E55353;
	box-shadow: 0 0 8px #E55353;
	animation: pulse 2s infinite;

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}
`

const VideoFeedContainer = styled.div`
	flex: 1;
	background: linear-gradient(135deg, #0A1628 0%, #1A2B42 100%);
	border: 1px solid rgba(47, 111, 219, 0.2);
	border-radius: 6px;
	overflow: hidden;
	position: relative;

	&::before {
		content: '';
		position: absolute;
		inset: 0;
		background: linear-gradient(
			90deg,
			rgba(47, 111, 219, 0.05) 0%,
			transparent 50%,
			rgba(47, 111, 219, 0.05) 100%
		);
		pointer-events: none;
	}
`

const VideoPlaceholder = styled.div`
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	height: 100%;
	color: rgba(47, 111, 219, 0.4);
	gap: 0.5rem;

	span {
		font-size: 0.8rem;
		font-weight: 500;
	}
`


export default VideoFeed;