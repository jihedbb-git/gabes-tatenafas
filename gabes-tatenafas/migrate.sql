-- ============================================================
-- GABES-TATENAFAS v2.0 — Full schema (PART 0 of the prompt)
-- All scientific ML/DL tables. Safe to run multiple times.
-- ============================================================

CREATE TABLE IF NOT EXISTS api_readings (
  id INT PRIMARY KEY AUTO_INCREMENT,
  city_id VARCHAR(50) NOT NULL, city_name VARCHAR(100),
  timestamp DATETIME NOT NULL,
  final_aqi FLOAT, final_category VARCHAR(50),
  final_pm25 FLOAT, final_pm10 FLOAT, final_no2 FLOAT, final_so2 FLOAT,
  final_o3 FLOAT, final_co FLOAT, final_temperature FLOAT, final_humidity FLOAT,
  final_wind_speed FLOAT, final_wind_direction FLOAT, final_pressure FLOAT,
  accuw_aqi FLOAT, accuw_category VARCHAR(50), accuw_pm25 FLOAT, accuw_pm10 FLOAT,
  accuw_no2 FLOAT, accuw_so2 FLOAT, accuw_o3 FLOAT, accuw_co FLOAT,
  accuw_temp FLOAT, accuw_feels_like FLOAT, accuw_humidity FLOAT, accuw_wind_speed FLOAT,
  accuw_wind_dir FLOAT, accuw_pressure FLOAT, accuw_visibility FLOAT, accuw_uv_index FLOAT,
  accuw_cloud_cover FLOAT, accuw_dew_point FLOAT, accuw_weather_text VARCHAR(100),
  accuw_forecast_1h FLOAT, accuw_forecast_3h FLOAT, accuw_forecast_6h FLOAT, accuw_forecast_12h FLOAT,
  accuw_available TINYINT(1) DEFAULT 0,
  iqair_aqi_us FLOAT, iqair_aqi_cn FLOAT, iqair_main_pollutant VARCHAR(20),
  iqair_pm25 FLOAT, iqair_pm10 FLOAT, iqair_temp FLOAT, iqair_humidity FLOAT,
  iqair_wind_speed FLOAT, iqair_wind_dir FLOAT, iqair_pressure FLOAT, iqair_available TINYINT(1) DEFAULT 0,
  waqi_aqi FLOAT, waqi_pm25 FLOAT, waqi_pm10 FLOAT, waqi_no2 FLOAT, waqi_so2 FLOAT,
  waqi_o3 FLOAT, waqi_co FLOAT, waqi_temp FLOAT, waqi_humidity FLOAT, waqi_wind FLOAT,
  waqi_available TINYINT(1) DEFAULT 0, data_quality_score FLOAT, source VARCHAR(20) DEFAULT 'api',
  INDEX(city_id, timestamp)
);

CREATE TABLE IF NOT EXISTS fuzzy_assessments (
  id INT PRIMARY KEY AUTO_INCREMENT, reading_id INT, city_id VARCHAR(50), timestamp DATETIME,
  pollution_input FLOAT, vulnerability_input FLOAT, symptom_severity_input FLOAT, alerts_24h_input FLOAT,
  fuzzy_score_type2 FLOAT, uncertainty_lower FLOAT, uncertainty_upper FLOAT, uncertainty_band FLOAT,
  risk_level ENUM('low','moderate','high','critical'), INDEX(city_id, timestamp)
);

CREATE TABLE IF NOT EXISTS model_predictions (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), timestamp DATETIME,
  horizon VARCHAR(10), model_name VARCHAR(100), predicted_aqi FLOAT, predicted_class VARCHAR(20),
  actual_aqi FLOAT, confidence_score FLOAT, uncertainty_lower FLOAT, uncertainty_upper FLOAT,
  trust_level ENUM('HIGH','MEDIUM','LOW'), latency_ms FLOAT,
  shap_values TEXT, lime_explanation TEXT, attention_weights TEXT,
  INDEX(city_id, timestamp, model_name)
);

CREATE TABLE IF NOT EXISTS model_performance (
  id INT PRIMARY KEY AUTO_INCREMENT, model_name VARCHAR(100), city_id VARCHAR(50),
  evaluated_at DATETIME, horizon VARCHAR(10), accuracy FLOAT, precision_macro FLOAT,
  recall_macro FLOAT, f1_macro FLOAT, mae FLOAT, rmse FLOAT, mape FLOAT, smape FLOAT,
  r_squared FLOAT, auc_roc FLOAT, avg_latency_ms FLOAT, cv_mean_f1 FLOAT, cv_std_f1 FLOAT,
  cv_mean_rmse FLOAT, cv_std_rmse FLOAT, improvement_vs_baseline FLOAT, roc_data TEXT,
  wilcoxon_pvalue FLOAT, optuna_best_params TEXT, INDEX(model_name, city_id)
);

CREATE TABLE IF NOT EXISTS ensemble_weights (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), updated_at DATETIME,
  weight_xgboost FLOAT DEFAULT 0.25, weight_random_forest FLOAT DEFAULT 0.25,
  weight_bilstm FLOAT DEFAULT 0.25, weight_xgb_bilstm FLOAT DEFAULT 0.25,
  score_xgboost FLOAT, score_rf FLOAT, score_bilstm FLOAT, score_xgb_bilstm FLOAT
);

CREATE TABLE IF NOT EXISTS drift_monitoring (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), detected_at DATETIME,
  drift_score FLOAT, kl_divergence FLOAT, statistical_shift FLOAT,
  drift_detected TINYINT(1) DEFAULT 0, retraining_triggered TINYINT(1) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anomaly_events (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), detected_at DATETIME,
  aqi_value FLOAT, anomaly_score FLOAT, anomaly_type VARCHAR(50),
  autoencoder_reconstruction_error FLOAT, isolation_forest_score FLOAT,
  description TEXT, excluded_from_training TINYINT(1) DEFAULT 1, INDEX(city_id, detected_at)
);

CREATE TABLE IF NOT EXISTS smart_alerts (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), triggered_at DATETIME,
  alert_level ENUM('INFO','WARNING','CRITICAL'), predicted_aqi FLOAT, confidence FLOAT,
  explanation TEXT, shap_top_features TEXT, lime_local_explanation TEXT,
  recommendations TEXT, acknowledged TINYINT(1) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS health_impact (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), timestamp DATETIME,
  aqi_value FLOAT, pm25_value FLOAT, so2_value FLOAT, vulnerable_population_pct FLOAT,
  health_impact_score FLOAT, health_risk_level VARCHAR(50), recommendations TEXT, INDEX(city_id, timestamp)
);

CREATE TABLE IF NOT EXISTS ablation_results (
  id INT PRIMARY KEY AUTO_INCREMENT, experiment_name VARCHAR(100), components_used TEXT,
  rmse FLOAT, f1 FLOAT, mae FLOAT, r_squared FLOAT, auc FLOAT, evaluated_at DATETIME
);

CREATE TABLE IF NOT EXISTS granger_causality (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), cause_variable VARCHAR(50),
  effect_variable VARCHAR(50), lag_hours INT, f_statistic FLOAT, p_value FLOAT,
  is_causal TINYINT(1), confidence_level FLOAT, computed_at DATETIME
);

CREATE TABLE IF NOT EXISTS optimization_history (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), cycle_date DATETIME,
  rmse_before FLOAT, rmse_after FLOAT, f1_before FLOAT, f1_after FLOAT,
  features_added TEXT, features_removed TEXT, improvement_pct FLOAT,
  optuna_trials INT, best_params TEXT
);

CREATE TABLE IF NOT EXISTS optuna_trials (
  id INT PRIMARY KEY AUTO_INCREMENT, model_name VARCHAR(100), city_id VARCHAR(50),
  trial_number INT, params TEXT, rmse FLOAT, f1 FLOAT, r_squared FLOAT,
  duration_seconds FLOAT, created_at DATETIME
);

CREATE TABLE IF NOT EXISTS attention_heatmaps (
  id INT PRIMARY KEY AUTO_INCREMENT, city_id VARCHAR(50), model_name VARCHAR(100),
  timestamp DATETIME, horizon VARCHAR(10), attention_matrix TEXT, peak_hour INT, peak_weight FLOAT
);

CREATE TABLE IF NOT EXISTS lime_explanations (
  id INT PRIMARY KEY AUTO_INCREMENT, prediction_id INT, city_id VARCHAR(50), timestamp DATETIME,
  feature_name VARCHAR(100), lime_weight FLOAT, feature_value FLOAT, direction ENUM('positive','negative')
);

CREATE TABLE IF NOT EXISTS websocket_sessions (
  id INT PRIMARY KEY AUTO_INCREMENT, session_id VARCHAR(100), city_id VARCHAR(50),
  connected_at DATETIME, last_update DATETIME, updates_sent INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS federated_rounds (
  id INT PRIMARY KEY AUTO_INCREMENT, round_number INT, participating_cities TEXT,
  global_rmse_before FLOAT, global_rmse_after FLOAT, aggregation_method VARCHAR(50), completed_at DATETIME
);
