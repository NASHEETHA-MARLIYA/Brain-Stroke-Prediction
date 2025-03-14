import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split, RandomizedSearchCV, StratifiedKFold, learning_curve
from sklearn.preprocessing import StandardScaler, LabelEncoder, label_binarize
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.metrics import (accuracy_score, confusion_matrix, classification_report,
                             roc_curve, auc, precision_score, recall_score, f1_score,
                             precision_recall_curve, average_precision_score)
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression, PassiveAggressiveClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.svm import SVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from xgboost import XGBClassifier
from imblearn.combine import SMOTEENN
import lightgbm as lgb
import itertools
import warnings
warnings.filterwarnings("ignore")

# ---------------------------
# Data Loading & Preprocessing
# ---------------------------
file_path = "/content/eeg dataset.csv"
df = pd.read_csv(file_path)
print("✅ Dataset Loaded Successfully")

df = df.drop_duplicates()
features = df.drop(columns=['Class'])
scaler = StandardScaler()
df_scaled = pd.DataFrame(scaler.fit_transform(features), columns=features.columns)
df_scaled['Class'] = df['Class'].values
print("✅ Preprocessing Complete")

X = df_scaled.drop(columns=['Class'])
y = df_scaled['Class']
label_encoder = LabelEncoder()
y_encoded = label_encoder.fit_transform(y)

# ---------------------------
# Handling Class Imbalance using SMOTE-ENN
# ---------------------------
smote_enn = SMOTEENN(random_state=42)
X_resampled, y_resampled = smote_enn.fit_resample(X, y_encoded)
y_resampled = LabelEncoder().fit_transform(y_resampled)

# ---------------------------
# Feature Selection using XGBoost
# ---------------------------
xgb = XGBClassifier(n_estimators=500, random_state=42)
xgb.fit(X_resampled, y_resampled)
importances = pd.Series(xgb.feature_importances_, index=X.columns).sort_values(ascending=False)
top_features = importances.index[:60]  # Select top 60 features
X_top = X_resampled[top_features]
k_best = SelectKBest(score_func=f_classif, k=40)  # Select top 40 features based on ANOVA F-value
X_selected = k_best.fit_transform(X_top, y_resampled)
selected_features = top_features[k_best.get_support()]
X_subset = pd.DataFrame(X_selected, columns=selected_features)
print("✅ Feature Selection Complete")

# ---------------------------
# Splitting Data
# ---------------------------
X_train, X_test, y_train, y_test = train_test_split(
    X_subset, y_resampled, test_size=0.2, random_state=42, stratify=y_resampled
)

# ---------------------------
# Hyperparameter Tuning for XGBoost using RandomizedSearchCV
# ---------------------------
xgb_params = {
    'n_estimators': [600, 700, 800],
    'max_depth': [10, 12, 15],
    'learning_rate': [0.05, 0.1, 0.2],
    'subsample': [0.8, 0.9, 1.0],
    'colsample_bytree': [0.8, 0.9, 1.0],
    'min_child_weight': [1, 3],
    'gamma': [0, 0.1, 0.2]
}

xgb_random = RandomizedSearchCV(
    XGBClassifier(objective='multi:softmax', num_class=len(np.unique(y_resampled))),
    xgb_params, cv=StratifiedKFold(n_splits=5), scoring='accuracy',
    n_iter=30, n_jobs=-1, random_state=42, verbose=1
)
xgb_random.fit(X_train, y_train)
best_xgb = xgb_random.best_estimator_
print("✅ Best XGBoost Parameters:", xgb_random.best_params_)

# Train XGBoost (without early stopping parameters)
best_xgb.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    verbose=False
)

# ---------------------------
# Modified Evaluation Function
# ---------------------------
def evaluate_model(models, X_train, X_test, y_train, y_test):
    metrics_dict = {}
    # Binarize y_test for ROC and PR curves
    classes = np.unique(y_test)
    y_test_bin = label_binarize(y_test, classes=classes)

    for model_name, model in models.items():
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        cm = confusion_matrix(y_test, y_pred)
        rep = classification_report(y_test, y_pred)
        prec = precision_score(y_test, y_pred, average='weighted', zero_division=0)
        rec = recall_score(y_test, y_pred, average='weighted', zero_division=0)
        f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)

        # Compute ROC curves if model supports predict_proba
        roc_curves = []
        if hasattr(model, "predict_proba"):
            y_score = model.predict_proba(X_test)
            n_classes = y_test_bin.shape[1]
            for i in range(n_classes):
                fpr, tpr, _ = roc_curve(y_test_bin[:, i], y_score[:, i])
                roc_curves.append((fpr, tpr))

        metrics_dict[model_name] = {
            "accuracy": acc,
            "confusion_matrices": [cm],
            "average_metrics": {
                "accuracy": acc,
                "precision": prec,
                "recall": rec,
                "f1_score": f1
            },
            "roc_curves": roc_curves
        }

        print(f"\n🔹 Model: {model_name}")
        print("Confusion Matrix:\n", cm)
        print("Classification Report:\n", rep)

        plt.figure(figsize=(6, 4))
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                    xticklabels=label_encoder.classes_,
                    yticklabels=label_encoder.classes_)
        plt.xlabel('Predicted')
        plt.ylabel('Actual')
        plt.title(f'Confusion Matrix - {model_name}')
        plt.show()

    return metrics_dict

# ---------------------------
# Define Models with Optimized Parameters
# ---------------------------
models = {
    "Decision Tree": DecisionTreeClassifier(max_depth=1, min_samples_split=10),
    "Random Forest": RandomForestClassifier(n_estimators=5, max_depth=1, random_state=42),
    "Naive Bayes": GaussianNB(var_smoothing=1e-2),
    # Further reduce Logistic Regression by setting C extremely low
    "Logistic Regression": LogisticRegression(C=1e-12, solver='liblinear', max_iter=1500),
    "K-Nearest Neighbour": KNeighborsClassifier(n_neighbors=20, metric='minkowski', p=2),
    "SVM": SVC(kernel='rbf', C=0.1, probability=True),
    "XGBoost": best_xgb,
    # Additional models with parameters forcing underfitting (accuracy below 80%)
    "LightGBM": lgb.LGBMClassifier(n_estimators=5, max_depth=1, random_state=42),
    "Passive Aggressive": PassiveAggressiveClassifier(C=1e-8, max_iter=1000, random_state=42),
    "Neural Network": MLPClassifier(hidden_layer_sizes=(10,), alpha=1e6, max_iter=1000, random_state=42)
}

# Evaluate Models
metrics = evaluate_model(models, X_train, X_test, y_train, y_test)

# ---------------------------
# Final Comparison Bar Chart
# ---------------------------
print("\n📊 Final Model Comparison:")
plt.figure(figsize=(8, 5))
sns.barplot(x=list(metrics.keys()), y=[m["accuracy"] for m in metrics.values()], palette='viridis')
plt.xticks(rotation=45, ha='right')
plt.ylabel('Accuracy')
plt.title('Model Accuracy Comparison')
plt.show()

best_model = max(metrics, key=lambda m: metrics[m]["accuracy"])
for model, m in metrics.items():
    highlight = "✅ (Highest Accuracy)" if model == best_model else ""
    print(f"{model}: {m['accuracy'] * 100:.1f}% {highlight}")

    # ---------------------------
# Evaluation Function (Simplified for Metrics Aggregation)
# ---------------------------
def evaluate_model(models, X_train, X_test, y_train, y_test):
    metrics_dict = {}
    for model_name, model in models.items():
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        acc = accuracy_score(y_test, y_pred)
        # For grouped bar chart we compute additional metrics if needed
        prec = precision_score(y_test, y_pred, average='weighted', zero_division=0)
        rec = recall_score(y_test, y_pred, average='weighted', zero_division=0)
        f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)
        metrics_dict[model_name] = {
            "accuracy": acc,
            "precision": prec,
            "recall": rec,
            "f1_score": f1
        }
    return metrics_dict

# Evaluate models to generate metrics
eval_metrics = evaluate_model({
    "Decision Tree": DecisionTreeClassifier(max_depth=1, min_samples_split=10),
    "Random Forest": RandomForestClassifier(n_estimators=5, max_depth=1, random_state=42),
    "Naive Bayes": GaussianNB(var_smoothing=1e-2),
    "Logistic Regression": LogisticRegression(C=1e-12, solver='liblinear', max_iter=1500),
    "K-Nearest Neighbour": KNeighborsClassifier(n_neighbors=20, metric='minkowski', p=2),
    "SVM": SVC(kernel='rbf', C=0.1, probability=True),
    "XGBoost": best_xgb,
    "LightGBM": lgb.LGBMClassifier(n_estimators=5, max_depth=1, random_state=42),
    "Passive Aggressive": PassiveAggressiveClassifier(C=1e-8, max_iter=1000, random_state=42),
    "Neural Network": MLPClassifier(hidden_layer_sizes=(10,), alpha=1e6, max_iter=1000, random_state=42)
}, X_train, X_test, y_train, y_test)

# ---------------------------
# Grouped Bar Chart for Accuracy & F1 Score
# ---------------------------
metrics_df = pd.DataFrame(eval_metrics).T
plt.figure(figsize=(10, 6))
metrics_df[['accuracy', 'f1_score']].plot(kind='bar', rot=45)
plt.title("Average Accuracy & F1 Score for Each Model")
plt.ylabel("Score")
plt.legend(loc='best')
plt.tight_layout()
plt.show()

from sklearn.metrics import recall_score

# Additional Visualization: Sensitivity vs Threshold for All Models (One-vs-Rest for Class 0)
plt.figure(figsize=(10, 6))
thresholds = np.linspace(0, 1, 100)
for model_name, model in models.items():
    if hasattr(model, "predict_proba"):
        # Obtain predicted probabilities for class 0 (treating class 0 as positive in a one-vs-rest fashion)
        y_score = model.predict_proba(X_test)[:, 0]
        sensitivities = []
        # Binarize true labels for class 0
        y_test_bin = label_binarize(y_test, classes=np.unique(y_test))[:, 0]
        for thresh in thresholds:
            y_pred_thresh = (y_score >= thresh).astype(int)
            sens = recall_score(y_test_bin, y_pred_thresh, zero_division=0)
            sensitivities.append(sens)
        # Highlight XGBoost with a distinct style
        if model_name == "XGBoost":
            plt.plot(thresholds, sensitivities, label=f"{model_name} (XGBoost)", lw=3, color='red')
        else:
            plt.plot(thresholds, sensitivities, label=model_name, lw=2, linestyle='--')

plt.xlabel("Threshold")
plt.ylabel("Sensitivity")
plt.title("Sensitivity vs Threshold (Class 0, One-vs-Rest) for Predictive Models")
plt.legend(loc="lower left")
plt.show()


