import { useEffect, useState } from "react";

type ListParams = {
  search?: string;
  start_date?: string;
  end_date?: string;
  limit?: number;
};

type ListResponse<T> = { rows: T[] };

export function useListQuery<T>(
  fetcher: (params: ListParams) => Promise<ListResponse<T>>,
  params: ListParams,
  errorMessage: string
) {
  const [rows, setRows] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    fetcher(params)
      .then((res) => setRows(res.rows))
      .catch(() => setError(errorMessage))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.search, params.start_date, params.end_date, params.limit]);

  return { rows, loading, error };
}
