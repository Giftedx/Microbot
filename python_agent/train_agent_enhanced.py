"""
Enhanced AI Agent Training Script with Monitoring and Performance Optimization.
Features real-time monitoring, health checks, automatic recovery, and metrics export.
"""

import os
import time
import signal
import threading
from datetime import datetime
from custom_env import CustomGameEnv
from stable_baselines3 import PPO
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.common.callbacks import BaseCallback
from monitoring import (
    initialize_monitoring, 
    RealTimeMonitor, 
    get_health_summary,
    record_error
)

# Create directories for logs and models
log_dir = "sb3_logs/"
model_dir = "sb3_models/"
monitoring_dir = "monitoring/"
os.makedirs(log_dir, exist_ok=True)
os.makedirs(model_dir, exist_ok=True)
os.makedirs(monitoring_dir, exist_ok=True)


class HealthCheckCallback(BaseCallback):
    """Custom callback for health monitoring and automatic recovery."""
    
    def __init__(self, check_interval=100, verbose=0):
        super().__init__(verbose)
        self.check_interval = check_interval
        self.last_health_check = 0
        self.health_failures = 0
        self.max_health_failures = 5
        
    def _on_step(self) -> bool:
        """Called after each step in the environment."""
        if self.n_calls % self.check_interval == 0:
            self._perform_health_check()
        return True
    
    def _perform_health_check(self):
        """Perform comprehensive health check."""
        try:
            health = get_health_summary()
            
            # Check for critical issues
            critical_issues = []
            
            if not health.get('zmq_connected', False):
                critical_issues.append("ZMQ connection lost")
            
            if health.get('error_count_last_minute', 0) > 10:
                critical_issues.append(f"High error rate: {health['error_count_last_minute']}/min")
            
            if health.get('last_observation_age_ms', 0) > 10000:
                critical_issues.append("Observation data too old")
            
            # Log health status
            if critical_issues:
                self.health_failures += 1
                error_msg = f"Health check failed: {', '.join(critical_issues)}"
                print(f"⚠️  {error_msg}")
                record_error("HEALTH_CHECK_FAILED", error_msg, health)
                
                if self.health_failures >= self.max_health_failures:
                    print("❌ Too many health check failures. Stopping training.")
                    return False
            else:
                self.health_failures = 0  # Reset counter on successful check
                if self.verbose > 0:
                    print(f"✅ Health check passed (Episode {health.get('total_episodes', 0)})")
                    
        except Exception as e:
            record_error("HEALTH_CHECK_ERROR", f"Health check failed with exception: {str(e)}")


class MetricsExportCallback(BaseCallback):
    """Callback for periodic metrics export and model saving."""
    
    def __init__(self, export_interval=1000, save_interval=5000, verbose=0):
        super().__init__(verbose)
        self.export_interval = export_interval
        self.save_interval = save_interval
        
    def _on_step(self) -> bool:
        """Called after each step."""
        # Export metrics periodically
        if self.n_calls % self.export_interval == 0:
            self._export_metrics()
        
        # Save model periodically
        if self.n_calls % self.save_interval == 0:
            self._save_model()
        
        return True
    
    def _export_metrics(self):
        """Export current metrics to file."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            metrics_file = os.path.join(monitoring_dir, f"metrics_{timestamp}.json")
            
            from monitoring import get_metrics_collector
            metrics = get_metrics_collector()
            metrics.export_metrics(metrics_file)
            
            if self.verbose > 0:
                print(f"📊 Metrics exported to {metrics_file}")
                
        except Exception as e:
            record_error("METRICS_EXPORT_ERROR", f"Failed to export metrics: {str(e)}")
    
    def _save_model(self):
        """Save current model checkpoint."""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_file = os.path.join(model_dir, f"checkpoint_{timestamp}_{self.n_calls}")
            
            if hasattr(self, 'model') and self.model:
                self.model.save(model_file)
                if self.verbose > 0:
                    print(f"💾 Model checkpoint saved: {model_file}")
                    
        except Exception as e:
            record_error("MODEL_SAVE_ERROR", f"Failed to save model: {str(e)}")


class TrainingManager:
    """Manages the complete training pipeline with monitoring and recovery."""
    
    def __init__(self, total_timesteps=10000, monitoring_enabled=True):
        self.total_timesteps = total_timesteps
        self.monitoring_enabled = monitoring_enabled
        self.monitor = None
        self.env = None
        self.model = None
        self.training_active = False
        self.start_time = None
        
        # Signal handling for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        print(f"\n🛑 Received signal {signum}. Shutting down gracefully...")
        self.stop_training()
    
    def initialize_environment(self):
        """Initialize the game environment with monitoring."""
        print("🎮 Initializing game environment...")
        
        try:
            # Initialize monitoring first
            if self.monitoring_enabled:
                print("📈 Initializing monitoring system...")
                self.metrics = initialize_monitoring(max_history=50000)
                self.monitor = RealTimeMonitor(self.metrics)
                self.monitor.start_monitoring(update_interval=10.0)
            
            # Create and wrap environment
            env = CustomGameEnv(render_mode='human' if self.monitoring_enabled else None)
            self.env = DummyVecEnv([lambda: env])
            
            # Optional environment validation (can be slow)
            # print("🔍 Validating environment...")
            # check_env(env, warn=True)
            
            print("✅ Environment initialized successfully")
            
        except Exception as e:
            error_msg = f"Failed to initialize environment: {str(e)}"
            print(f"❌ {error_msg}")
            record_error("ENV_INIT_ERROR", error_msg)
            raise
    
    def initialize_model(self, model_path=None):
        """Initialize or load the PPO model."""
        print("🧠 Initializing AI model...")
        
        try:
            if model_path and os.path.exists(model_path):
                print(f"📁 Loading existing model from {model_path}")
                self.model = PPO.load(model_path, env=self.env)
            else:
                print("🆕 Creating new PPO model...")
                self.model = PPO(
                    "MultiInputPolicy", 
                    self.env, 
                    verbose=1, 
                    tensorboard_log=log_dir,
                    learning_rate=3e-4,
                    n_steps=2048,
                    batch_size=64,
                    n_epochs=10,
                    gamma=0.99,
                    gae_lambda=0.95,
                    clip_range=0.2,
                    ent_coef=0.01,
                    vf_coef=0.5,
                    max_grad_norm=0.5
                )
            
            print("✅ Model initialized successfully")
            
        except Exception as e:
            error_msg = f"Failed to initialize model: {str(e)}"
            print(f"❌ {error_msg}")
            record_error("MODEL_INIT_ERROR", error_msg)
            raise
    
    def start_training(self):
        """Start the training process with monitoring and callbacks."""
        print(f"🚀 Starting training for {self.total_timesteps:,} timesteps...")
        self.start_time = time.time()
        self.training_active = True
        
        try:
            # Setup callbacks
            callbacks = []
            
            if self.monitoring_enabled:
                health_callback = HealthCheckCallback(check_interval=100, verbose=1)
                metrics_callback = MetricsExportCallback(
                    export_interval=2000, 
                    save_interval=10000, 
                    verbose=1
                )
                callbacks = [health_callback, metrics_callback]
            
            # Train the model
            self.model.learn(
                total_timesteps=self.total_timesteps,
                callback=callbacks,
                tb_log_name=f"PPO_training_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                reset_num_timesteps=False
            )
            
            print("🎉 Training completed successfully!")
            
        except KeyboardInterrupt:
            print("\n⏸️  Training interrupted by user")
        except Exception as e:
            error_msg = f"Training failed: {str(e)}"
            print(f"❌ {error_msg}")
            record_error("TRAINING_ERROR", error_msg)
        finally:
            self.training_active = False
            self._cleanup_training()
    
    def _cleanup_training(self):
        """Clean up resources after training."""
        print("🧹 Cleaning up training resources...")
        
        try:
            # Save final model
            if self.model:
                final_model_path = os.path.join(model_dir, f"final_model_{int(time.time())}")
                self.model.save(final_model_path)
                print(f"💾 Final model saved: {final_model_path}")
            
            # Export final metrics
            if self.monitoring_enabled and hasattr(self, 'metrics'):
                final_metrics_path = os.path.join(monitoring_dir, f"final_metrics_{int(time.time())}.json")
                self.metrics.export_metrics(final_metrics_path)
                print(f"📊 Final metrics exported: {final_metrics_path}")
                
                # Save dashboard
                if self.monitor:
                    dashboard_path = os.path.join(monitoring_dir, f"final_dashboard_{int(time.time())}.png")
                    self.monitor.save_dashboard(dashboard_path)
                    print(f"📈 Dashboard saved: {dashboard_path}")
            
            # Close environment
            if self.env:
                self.env.close()
                print("🎮 Environment closed")
            
            # Stop monitoring
            if self.monitor:
                self.monitor.stop_monitoring()
                print("📈 Monitoring stopped")
            
            # Print training summary
            if self.start_time:
                training_duration = time.time() - self.start_time
                print(f"⏱️  Total training time: {training_duration:.2f} seconds")
                print(f"📊 Average timesteps/second: {self.total_timesteps/training_duration:.2f}")
            
        except Exception as e:
            record_error("CLEANUP_ERROR", f"Error during cleanup: {str(e)}")
    
    def stop_training(self):
        """Stop training gracefully."""
        self.training_active = False
        print("🛑 Training stop requested...")
    
    def run_evaluation(self, num_episodes=5):
        """Run evaluation episodes to test model performance."""
        if not self.model:
            print("❌ No model available for evaluation")
            return
        
        print(f"🧪 Running evaluation for {num_episodes} episodes...")
        
        total_rewards = []
        
        for episode in range(num_episodes):
            obs = self.env.reset()
            episode_reward = 0
            done = False
            
            while not done:
                action, _states = self.model.predict(obs, deterministic=True)
                obs, reward, done, info = self.env.step(action)
                episode_reward += reward
                
                if done:
                    break
            
            total_rewards.append(episode_reward)
            print(f"📊 Episode {episode + 1}: Reward = {episode_reward:.2f}")
        
        avg_reward = sum(total_rewards) / len(total_rewards)
        print(f"🎯 Average evaluation reward: {avg_reward:.2f}")
        return avg_reward


def main():
    """Main training function."""
    print("🤖 Microbot AI Agent Training System")
    print("=" * 50)
    
    # Configuration
    TOTAL_TIMESTEPS = 50000
    ENABLE_MONITORING = True
    MODEL_PATH = None  # Set to load existing model
    
    # Initialize training manager
    manager = TrainingManager(
        total_timesteps=TOTAL_TIMESTEPS,
        monitoring_enabled=ENABLE_MONITORING
    )
    
    try:
        # Setup
        manager.initialize_environment()
        manager.initialize_model(MODEL_PATH)
        
        # Run training
        manager.start_training()
        
        # Optional evaluation
        print("\n" + "=" * 50)
        print("🧪 Running post-training evaluation...")
        manager.run_evaluation(num_episodes=3)
        
    except Exception as e:
        print(f"❌ Fatal error in main: {str(e)}")
        record_error("MAIN_ERROR", str(e))
    finally:
        print("\n🏁 Training session complete")
        print(f"📁 Check {log_dir} for TensorBoard logs")
        print(f"💾 Check {model_dir} for saved models")
        if ENABLE_MONITORING:
            print(f"📊 Check {monitoring_dir} for monitoring data")


if __name__ == '__main__':
    main() 