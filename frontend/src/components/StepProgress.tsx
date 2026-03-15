interface Props {
  currentStep: number;
  totalSteps: number;
  stepLabel: string;
  isRecap: boolean;
  completedCount?: number;
}

export function StepProgress({
  currentStep,
  totalSteps,
  stepLabel,
  isRecap,
  completedCount,
}: Props) {
  const useCompletedCount = typeof completedCount === "number";
  const boundedCompleted = useCompletedCount
    ? Math.max(0, Math.min(completedCount, totalSteps))
    : null;

  return (
    <div className="step-progress">
      <div className="step-progress__bar">
        {Array.from({ length: totalSteps }, (_, i) => {
          const filled = isRecap
            ? true
            : boundedCompleted !== null
              ? i < boundedCompleted
              : i <= currentStep;
          const active = !isRecap && boundedCompleted !== null
            ? boundedCompleted > 0 && i === boundedCompleted - 1
            : i === currentStep;
          return (
            <div
              key={i}
              className={
                "step-progress__dot" +
                (filled ? " step-progress__dot--filled" : "") +
                (active ? " step-progress__dot--active" : "")
              }
              aria-label={`Step ${i + 1}${filled ? " (completed)" : ""}`}
            />
          );
        })}
      </div>
      <span className="step-progress__label">
        {isRecap ? "Complete!" : stepLabel}
      </span>
    </div>
  );
}
