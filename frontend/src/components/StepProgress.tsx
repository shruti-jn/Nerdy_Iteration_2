interface Props {
  currentStep: number;
  totalSteps: number;
  stepLabel: string;
  isRecap: boolean;
}

export function StepProgress({ currentStep, totalSteps, stepLabel, isRecap }: Props) {
  return (
    <div className="step-progress">
      <div className="step-progress__bar">
        {Array.from({ length: totalSteps }, (_, i) => {
          const filled = isRecap || i <= currentStep;
          const active = !isRecap && i === currentStep;
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
