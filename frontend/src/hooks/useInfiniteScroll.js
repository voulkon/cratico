import { useEffect, useRef } from 'react';

const useInfiniteScroll = ({
  hasMore,
  loading,
  loadingMore,
  onLoadMore,
  threshold = 0.1,
  enabled = true,
  rootRef = null,
}) => {
  const sentinelRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          onLoadMore();
        }
      },
      { threshold, root: rootRef?.current ?? null }
    );

    const currentTarget = sentinelRef.current;
    if (currentTarget) observer.observe(currentTarget);

    return () => {
      if (currentTarget) observer.unobserve(currentTarget);
    };
  }, [enabled, hasMore, loadingMore, loading, onLoadMore, threshold, rootRef]);

  return { sentinelRef };
};

export default useInfiniteScroll;
