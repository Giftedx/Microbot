"""
Monitoring and metrics collection system for Microbot AI agent.
Tracks performance, health, and training progress with real-time visualization.
"""

import json
import time
import threading
import collections
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
import logging

try:
    import matplotlib.pyplot as plt
    import matplotlib.animation as animation
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class PerformanceMetrics:
    """Performance metrics for a single timestep."""
    timestamp: float
    episode: int
    step: int
    reward: float
    cumulative_reward: float
    player_health: float
    player_max_health: float
    action_taken: str
    action_success: bool
    observation_latency_ms: float
    action_latency_ms: float
    fps: float
    memory_usage_mb: float
    cpu_usage_percent: float


@dataclass
class AgentHealth:
    """Health status of the AI agent system."""
    timestamp: float
    zmq_connected: bool
    game_logged_in: bool
    last_observation_age_ms: float
    last_action_age_ms: float
    error_count_last_minute: int
    warning_count_last_minute: int
    connection_failures: int
    total_episodes: int
    total_steps: int


class MetricsCollector:
    """Collects and stores performance metrics."""
    
    def __init__(self, max_history=10000):
        self.max_history = max_history
        self.metrics_history: List[PerformanceMetrics] = []
        self.health_history: List[AgentHealth] = []
        self.episode_rewards: Dict[int, List[float]] = collections.defaultdict(list)
        self.episode_lengths: Dict[int, int] = {}
        self.error_log: List[Dict] = []
        self.start_time = time.time()
        self._lock = threading.Lock()
        
        # Performance tracking
        self.observation_times = collections.deque(maxlen=100)
        self.action_times = collections.deque(maxlen=100)
        self.frame_times = collections.deque(maxlen=60)
        
        # Error tracking
        self.recent_errors = collections.deque(maxlen=100)
        self.recent_warnings = collections.deque(maxlen=100)
        
        # Health status
        self.last_observation_time = 0
        self.last_action_time = 0
        self.connection_failures = 0
        self.total_episodes = 0
        self.total_steps = 0
        
        # Setup logging
        self.logger = logging.getLogger('microbot_monitor')
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def record_observation_time(self, duration_ms: float):
        """Record time taken to get observation."""
        with self._lock:
            self.observation_times.append(duration_ms)
            self.last_observation_time = time.time()
    
    def record_action_time(self, duration_ms: float):
        """Record time taken to execute action."""
        with self._lock:
            self.action_times.append(duration_ms)
            self.last_action_time = time.time()
    
    def record_frame_time(self, duration_ms: float):
        """Record time for complete frame processing."""
        with self._lock:
            self.frame_times.append(duration_ms)
    
    def record_error(self, error_type: str, message: str, details: Optional[Dict] = None):
        """Record an error occurrence."""
        with self._lock:
            error_entry = {
                'timestamp': time.time(),
                'type': error_type,
                'message': message,
                'details': details or {}
            }
            self.error_log.append(error_entry)
            self.recent_errors.append(time.time())
            self.logger.error(f"{error_type}: {message}")
    
    def record_warning(self, warning_type: str, message: str):
        """Record a warning occurrence."""
        with self._lock:
            self.recent_warnings.append(time.time())
            self.logger.warning(f"{warning_type}: {message}")
    
    def record_connection_failure(self):
        """Record a connection failure."""
        with self._lock:
            self.connection_failures += 1
            self.record_error("CONNECTION_FAILURE", "ZMQ connection failed")
    
    def record_metrics(self, episode: int, step: int, reward: float, 
                      cumulative_reward: float, player_health: float, 
                      player_max_health: float, action_taken: str, 
                      action_success: bool, game_state: Dict[str, Any]):
        """Record a complete set of metrics for a timestep."""
        
        current_time = time.time()
        
        # Calculate latencies
        obs_latency = np.mean(self.observation_times) if self.observation_times else 0
        action_latency = np.mean(self.action_times) if self.action_times else 0
        fps = 1000 / np.mean(self.frame_times) if self.frame_times else 0
        
        # Get system metrics if available
        memory_usage = 0
        cpu_usage = 0
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                memory_usage = process.memory_info().rss / 1024 / 1024  # MB
                cpu_usage = process.cpu_percent()
            except:
                pass
        
        metrics = PerformanceMetrics(
            timestamp=current_time,
            episode=episode,
            step=step,
            reward=reward,
            cumulative_reward=cumulative_reward,
            player_health=player_health,
            player_max_health=player_max_health,
            action_taken=action_taken,
            action_success=action_success,
            observation_latency_ms=obs_latency,
            action_latency_ms=action_latency,
            fps=fps,
            memory_usage_mb=memory_usage,
            cpu_usage_percent=cpu_usage
        )
        
        with self._lock:
            self.metrics_history.append(metrics)
            if len(self.metrics_history) > self.max_history:
                self.metrics_history.pop(0)
            
            # Track episode-specific metrics
            self.episode_rewards[episode].append(reward)
            self.episode_lengths[episode] = step
            
            # Update counters
            if step == 0:  # New episode
                self.total_episodes += 1
            self.total_steps += 1
    
    def get_health_status(self) -> AgentHealth:
        """Get current health status of the system."""
        current_time = time.time()
        cutoff_time = current_time - 60  # Last minute
        
        error_count = sum(1 for t in self.recent_errors if t > cutoff_time)
        warning_count = sum(1 for t in self.recent_warnings if t > cutoff_time)
        
        # Determine connection status (simplified)
        zmq_connected = (current_time - self.last_observation_time) < 10
        
        return AgentHealth(
            timestamp=current_time,
            zmq_connected=zmq_connected,
            game_logged_in=zmq_connected,  # Simplified assumption
            last_observation_age_ms=(current_time - self.last_observation_time) * 1000,
            last_action_age_ms=(current_time - self.last_action_time) * 1000,
            error_count_last_minute=error_count,
            warning_count_last_minute=warning_count,
            connection_failures=self.connection_failures,
            total_episodes=self.total_episodes,
            total_steps=self.total_steps
        )
    
    def get_episode_summary(self, episode: int) -> Dict[str, Any]:
        """Get summary statistics for an episode."""
        if episode not in self.episode_rewards:
            return {}
        
        rewards = self.episode_rewards[episode]
        return {
            'episode': episode,
            'total_reward': sum(rewards),
            'average_reward': np.mean(rewards),
            'length': self.episode_lengths.get(episode, 0),
            'min_reward': min(rewards) if rewards else 0,
            'max_reward': max(rewards) if rewards else 0
        }
    
    def get_recent_performance(self, minutes: int = 10) -> Dict[str, Any]:
        """Get performance statistics for the last N minutes."""
        cutoff_time = time.time() - (minutes * 60)
        recent_metrics = [m for m in self.metrics_history if m.timestamp > cutoff_time]
        
        if not recent_metrics:
            return {}
        
        rewards = [m.reward for m in recent_metrics]
        health_values = [m.player_health for m in recent_metrics]
        latencies = [m.observation_latency_ms for m in recent_metrics]
        
        return {
            'period_minutes': minutes,
            'total_steps': len(recent_metrics),
            'average_reward': np.mean(rewards),
            'total_reward': sum(rewards),
            'average_health': np.mean(health_values),
            'average_latency_ms': np.mean(latencies),
            'fps': np.mean([m.fps for m in recent_metrics]),
            'memory_usage_mb': recent_metrics[-1].memory_usage_mb if recent_metrics else 0,
            'cpu_usage_percent': recent_metrics[-1].cpu_usage_percent if recent_metrics else 0
        }
    
    def export_metrics(self, filepath: str):
        """Export metrics to JSON file."""
        with self._lock:
            data = {
                'export_timestamp': time.time(),
                'start_time': self.start_time,
                'metrics': [asdict(m) for m in self.metrics_history],
                'episode_summaries': [self.get_episode_summary(ep) 
                                    for ep in self.episode_rewards.keys()],
                'health_status': asdict(self.get_health_status()),
                'recent_performance': self.get_recent_performance(),
                'error_log': self.error_log[-100:]  # Last 100 errors
            }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        self.logger.info(f"Metrics exported to {filepath}")


class RealTimeMonitor:
    """Real-time monitoring dashboard with live plots."""
    
    def __init__(self, metrics_collector: MetricsCollector):
        self.metrics = metrics_collector
        self.running = False
        self.update_thread = None
        
        if not MATPLOTLIB_AVAILABLE:
            self.logger = logging.getLogger('microbot_monitor')
            self.logger.warning("Matplotlib not available, visual monitoring disabled")
            return
        
        # Setup plots
        self.fig, self.axes = plt.subplots(2, 2, figsize=(12, 8))
        self.fig.suptitle('Microbot AI Agent - Real-Time Monitoring')
        
        # Reward plot
        self.ax_reward = self.axes[0, 0]
        self.ax_reward.set_title('Episode Rewards')
        self.ax_reward.set_xlabel('Episode')
        self.ax_reward.set_ylabel('Total Reward')
        
        # Health plot
        self.ax_health = self.axes[0, 1]
        self.ax_health.set_title('Player Health')
        self.ax_health.set_xlabel('Time')
        self.ax_health.set_ylabel('Health %')
        
        # Performance plot
        self.ax_perf = self.axes[1, 0]
        self.ax_perf.set_title('System Performance')
        self.ax_perf.set_xlabel('Time')
        self.ax_perf.set_ylabel('FPS / Latency(ms)')
        
        # System resources plot
        self.ax_sys = self.axes[1, 1]
        self.ax_sys.set_title('System Resources')
        self.ax_sys.set_xlabel('Time')
        self.ax_sys.set_ylabel('Usage %')
        
        plt.tight_layout()
    
    def start_monitoring(self, update_interval=5.0):
        """Start real-time monitoring in a separate thread."""
        if not MATPLOTLIB_AVAILABLE:
            return
        
        self.running = True
        self.update_thread = threading.Thread(
            target=self._monitoring_loop, 
            args=(update_interval,)
        )
        self.update_thread.start()
    
    def stop_monitoring(self):
        """Stop real-time monitoring."""
        self.running = False
        if self.update_thread:
            self.update_thread.join()
    
    def _monitoring_loop(self, interval):
        """Main monitoring loop."""
        while self.running:
            try:
                self._update_plots()
                time.sleep(interval)
            except Exception as e:
                self.metrics.record_error("MONITORING_ERROR", str(e))
                time.sleep(interval)
    
    def _update_plots(self):
        """Update all monitoring plots."""
        if not MATPLOTLIB_AVAILABLE:
            return
        
        with self.metrics._lock:
            metrics = self.metrics.metrics_history.copy()
        
        if not metrics:
            return
        
        # Clear axes
        for ax in self.axes.flat:
            ax.clear()
        
        # Episode rewards
        episode_rewards = {}
        for m in metrics:
            if m.episode not in episode_rewards:
                episode_rewards[m.episode] = []
            episode_rewards[m.episode].append(m.reward)
        
        if episode_rewards:
            episodes = list(episode_rewards.keys())
            total_rewards = [sum(episode_rewards[ep]) for ep in episodes]
            
            self.ax_reward.plot(episodes, total_rewards, 'b-o')
            self.ax_reward.set_title('Episode Rewards')
            self.ax_reward.set_xlabel('Episode')
            self.ax_reward.set_ylabel('Total Reward')
            self.ax_reward.grid(True)
        
        # Player health over time
        if len(metrics) > 1:
            times = [(m.timestamp - metrics[0].timestamp) / 60 for m in metrics]  # Minutes
            health_pct = [(m.player_health / m.player_max_health) * 100 for m in metrics]
            
            self.ax_health.plot(times, health_pct, 'g-')
            self.ax_health.set_title('Player Health')
            self.ax_health.set_xlabel('Time (minutes)')
            self.ax_health.set_ylabel('Health %')
            self.ax_health.set_ylim(0, 100)
            self.ax_health.grid(True)
        
        # Performance metrics
        if len(metrics) > 1:
            times = [(m.timestamp - metrics[0].timestamp) / 60 for m in metrics]
            fps = [m.fps for m in metrics]
            latency = [m.observation_latency_ms for m in metrics]
            
            ax2 = self.ax_perf.twinx()
            line1 = self.ax_perf.plot(times, fps, 'b-', label='FPS')
            line2 = ax2.plot(times, latency, 'r-', label='Latency (ms)')
            
            self.ax_perf.set_xlabel('Time (minutes)')
            self.ax_perf.set_ylabel('FPS', color='b')
            ax2.set_ylabel('Latency (ms)', color='r')
            self.ax_perf.set_title('System Performance')
            
            lines = line1 + line2
            labels = [l.get_label() for l in lines]
            self.ax_perf.legend(lines, labels, loc='upper left')
            self.ax_perf.grid(True)
        
        # System resources
        if len(metrics) > 1:
            times = [(m.timestamp - metrics[0].timestamp) / 60 for m in metrics]
            memory = [m.memory_usage_mb for m in metrics]
            cpu = [m.cpu_usage_percent for m in metrics]
            
            ax2 = self.ax_sys.twinx()
            line1 = self.ax_sys.plot(times, cpu, 'orange', label='CPU %')
            line2 = ax2.plot(times, memory, 'purple', label='Memory (MB)')
            
            self.ax_sys.set_xlabel('Time (minutes)')
            self.ax_sys.set_ylabel('CPU %', color='orange')
            ax2.set_ylabel('Memory (MB)', color='purple')
            self.ax_sys.set_title('System Resources')
            
            lines = line1 + line2
            labels = [l.get_label() for l in lines]
            self.ax_sys.legend(lines, labels, loc='upper left')
            self.ax_sys.grid(True)
        
        plt.tight_layout()
        plt.pause(0.01)  # Allow GUI to update
    
    def save_dashboard(self, filepath: str):
        """Save current dashboard as image."""
        if MATPLOTLIB_AVAILABLE:
            self.fig.savefig(filepath, dpi=150, bbox_inches='tight')


# Numpy import with fallback
try:
    import numpy as np
except ImportError:
    # Minimal numpy replacement for basic functions
    class MinimalNumpy:
        @staticmethod
        def mean(arr):
            return sum(arr) / len(arr) if arr else 0
        
        @staticmethod
        def min(arr):
            return min(arr) if arr else 0
        
        @staticmethod
        def max(arr):
            return max(arr) if arr else 0
    
    np = MinimalNumpy()


# Global metrics collector instance
_global_metrics = None

def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = MetricsCollector()
    return _global_metrics


def initialize_monitoring(max_history=10000) -> MetricsCollector:
    """Initialize the global monitoring system."""
    global _global_metrics
    _global_metrics = MetricsCollector(max_history)
    return _global_metrics


# Convenience functions for common operations
def record_performance(episode: int, step: int, reward: float, **kwargs):
    """Convenience function to record performance metrics."""
    metrics = get_metrics_collector()
    metrics.record_metrics(episode, step, reward, **kwargs)


def record_error(error_type: str, message: str, details=None):
    """Convenience function to record errors."""
    metrics = get_metrics_collector()
    metrics.record_error(error_type, message, details)


def get_health_summary() -> Dict[str, Any]:
    """Get a summary of system health."""
    metrics = get_metrics_collector()
    health = metrics.get_health_status()
    return asdict(health)


if __name__ == "__main__":
    # Demo monitoring system
    print("Microbot Monitoring System Demo")
    
    # Initialize monitoring
    metrics = initialize_monitoring()
    monitor = RealTimeMonitor(metrics)
    
    if MATPLOTLIB_AVAILABLE:
        monitor.start_monitoring(update_interval=2.0)
    
    # Simulate some data
    import random
    
    for episode in range(5):
        cumulative_reward = 0
        for step in range(50):
            reward = random.uniform(-1, 5)
            cumulative_reward += reward
            health = max(10, 100 - step)  # Decreasing health
            
            metrics.record_metrics(
                episode=episode,
                step=step,
                reward=reward,
                cumulative_reward=cumulative_reward,
                player_health=health,
                player_max_health=100,
                action_taken=random.choice(["attack", "eat", "move", "noop"]),
                action_success=random.choice([True, False]),
                game_state={}
            )
            
            time.sleep(0.1)
    
    # Export metrics
    metrics.export_metrics("demo_metrics.json")
    
    if MATPLOTLIB_AVAILABLE:
        monitor.save_dashboard("demo_dashboard.png")
        input("Press Enter to stop monitoring...")
        monitor.stop_monitoring()
    
    print("Demo completed!") 