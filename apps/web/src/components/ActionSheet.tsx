export function ActionSheet({
  title,
  description,
  primaryText,
  onPrimary,
  onClose,
}: {
  title: string;
  description: string;
  primaryText: string;
  onPrimary: () => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute inset-0 bg-black/40 flex items-end z-30" onClick={onClose}>
      <div className="w-full rounded-t-3xl bg-white p-5" onClick={(e) => e.stopPropagation()}>
        <div className="w-10 h-1 rounded-full bg-slate-200 mx-auto mb-4" />
        <h3 className="text-lg font-bold">{title}</h3>
        <p className="text-sm text-slate-500 mt-2 leading-relaxed">{description}</p>
        <div className="flex gap-2 mt-5">
          <button type="button" onClick={onClose} className="flex-1 rounded-xl border border-slate-200 py-3 text-sm">
            取消
          </button>
          <button type="button" onClick={onPrimary} className="flex-1 rounded-xl bg-indigo-600 text-white py-3 text-sm">
            {primaryText}
          </button>
        </div>
      </div>
    </div>
  );
}
