"use client";
import { useState, useCallback } from "react";
import { toast } from "sonner";

export function useSubmit<T = void>() {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submit = useCallback(
    async <R = T>(
      action: () => Promise<R>,
      options?: {
        successMessage?: string;
        errorMessage?: string;
        onSuccess?: (result: R) => void;
        onError?: (err: unknown) => void;
      }
    ): Promise<R | undefined> => {
      if (isSubmitting) return undefined;
      setIsSubmitting(true);
      try {
        const result = await action();
        if (options?.successMessage !== "") {
          toast.success(options?.successMessage || "저장되었습니다");
        }
        options?.onSuccess?.(result);
        return result;
      } catch (err: unknown) {
        const msg =
          options?.errorMessage ||
          (err as { message?: string })?.message ||
          "오류가 발생했습니다";
        toast.error(msg);
        options?.onError?.(err);
        return undefined;
      } finally {
        setIsSubmitting(false);
      }
    },
    [isSubmitting]
  );

  return { submit, isSubmitting };
}
